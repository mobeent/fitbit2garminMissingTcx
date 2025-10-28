import json
import os
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime


def create_tcx(log_id: str):
    # === CONFIG ===
    HEART_RATE_FILE = f"f2g/{log_id}/exercise-heart-rate.json"
    CALORIES_FILE = f"f2g/{log_id}/exercise-calories.json"
    ACTIVITY_FILE = f"f2g/{log_id}/exercise-activity.json"
    OUTPUT_FILE = f"f2g/exercise-{log_id}.tcx"

    # === Mapping Fitbit activity names to Garmin TCX Sport types ===
    FITBIT_TO_GARMIN_SPORT = {
        "Run": "Running",
        "Walk": "Walking",
        "Hike": "Hiking",
        "Bike": "Biking",
        "Swim": "Swimming",
        "Treadmill": "Running",
        "Elliptical": "Other",
        "Yoga": "Other",
        "Strength Training": "Other",
        "Workout": "Other",
        # Add more as needed
    }

    DISTANCE_RELEVANT_ACTIVITIES = {
        "Run",
        "Walk",
        "Hike",
        "Bike",
        "Treadmill",
        "Swim",
        "Sport",
    }

    DEFAULT_STRIDE_LENGTH_M = 0.762  # average adult stride

    # === Load all data ===
    with open(HEART_RATE_FILE, "r") as f:
        hr_data = json.load(f)

    try:
        with open(CALORIES_FILE, "r") as f:
            calorie_data = json.load(f)
            calories_available = True
    except FileNotFoundError:
        print("⚠️  Calories file not found. Skipping per-minute calorie data.")
        calorie_data = {}
        calories_available = False

    with open(ACTIVITY_FILE, "r") as f:
        activity = json.load(f)

    # === Parse activity metadata ===
    start_time_str = activity["startTime"]
    start_time = datetime.fromisoformat(start_time_str)  # timezone-aware
    tzinfo = start_time.tzinfo

    duration_ms = activity["duration"]
    total_seconds = duration_ms / 1000.0
    calories_total = activity["calories"]

    # Determine Fitbit activity type and Garmin sport
    fitbit_activity = activity.get("activityName", "Workout")
    garmin_sport = FITBIT_TO_GARMIN_SPORT.get(fitbit_activity, "Other")

    # === Handle distance or estimate from steps ===
    distance_km = activity.get("distance", 0.0)
    steps = activity.get("steps", 0)

    if distance_km == 0.0:
        if steps > 0 and fitbit_activity in DISTANCE_RELEVANT_ACTIVITIES:
            distance_km = (steps * DEFAULT_STRIDE_LENGTH_M) / 1000.0
            print(
                f"ℹ️  Estimated distance from {steps} steps for '{fitbit_activity}': {distance_km:.2f} km"
            )
        else:
            print(f"⚠️  No distance found for '{fitbit_activity}' — using 0.0 km.")

    # === Parse heart rate dataset ===
    hr_dataset = hr_data["activities-heart-intraday"]["dataset"]
    hr_times = []
    hr_values = []

    date_str = hr_data["activities-heart"][0]["dateTime"]

    for entry in hr_dataset:
        dt_local_naive = datetime.strptime(
            f"{date_str} {entry['time']}", "%Y-%m-%d %H:%M:%S"
        )
        dt_local = dt_local_naive.replace(tzinfo=tzinfo)
        hr_times.append(dt_local)
        hr_values.append(entry["value"])

    max_hr = max(hr_values)
    avg_hr = round(statistics.mean(hr_values))

    # === Parse calorie dataset (1-min resolution) if available ===
    calorie_map = {}
    if calories_available:
        try:
            for entry in calorie_data["activities-calories-intraday"]["dataset"]:
                dt_local_naive = datetime.strptime(
                    f"{calorie_data['activities-calories'][0]['dateTime']} {entry['time']}",
                    "%Y-%m-%d %H:%M:%S",
                )
                dt_local = dt_local_naive.replace(tzinfo=tzinfo)
                calorie_map[dt_local.replace(second=0, microsecond=0)] = entry["value"]
        except Exception as e:
            print(f"⚠️  Failed to parse calorie data: {e}")
            calories_available = False

    # === TCX XML Setup ===
    ns = {
        "": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    ET.register_namespace("", ns[""])
    ET.register_namespace("ext", ns["ext"])
    ET.register_namespace("xsi", ns["xsi"])

    tcx = ET.Element(
        "TrainingCenterDatabase",
        {
            "xmlns": ns[""],
            "xmlns:xsi": ns["xsi"],
            "xsi:schemaLocation": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 "
            "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd",
        },
    )

    activities = ET.SubElement(tcx, "Activities")
    activity_elem = ET.SubElement(activities, "Activity", Sport=garmin_sport)
    ET.SubElement(activity_elem, "Id").text = start_time.strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    lap = ET.SubElement(
        activity_elem, "Lap", StartTime=start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    )
    ET.SubElement(lap, "TotalTimeSeconds").text = f"{total_seconds:.1f}"
    ET.SubElement(lap, "DistanceMeters").text = f"{distance_km * 1000:.2f}"
    ET.SubElement(lap, "Calories").text = str(calories_total)

    avg_elem = ET.SubElement(lap, "AverageHeartRateBpm")
    ET.SubElement(avg_elem, "Value").text = str(avg_hr)

    max_elem = ET.SubElement(lap, "MaximumHeartRateBpm")
    ET.SubElement(max_elem, "Value").text = str(max_hr)

    ET.SubElement(lap, "Intensity").text = "Active"
    ET.SubElement(lap, "TriggerMethod").text = "Manual"

    # === Build Trackpoints (with heart rate and optional calorie data) ===
    track = ET.SubElement(lap, "Track")

    for ts, hr in zip(hr_times, hr_values):
        tp = ET.SubElement(track, "Trackpoint")
        ET.SubElement(tp, "Time").text = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        hr_elem = ET.SubElement(tp, "HeartRateBpm")
        ET.SubElement(hr_elem, "Value").text = str(hr)

        if calories_available:
            min_key = ts.replace(second=0, microsecond=0)
            cal_per_min = calorie_map.get(min_key)
            if cal_per_min:
                cal_per_sec = cal_per_min / 60.0
                ext = ET.SubElement(tp, "Extensions")
                tpx = ET.SubElement(
                    ext, "{http://www.garmin.com/xmlschemas/ActivityExtension/v2}TPX"
                )
                ET.SubElement(
                    tpx,
                    "{http://www.garmin.com/xmlschemas/ActivityExtension/v2}Calories",
                ).text = f"{cal_per_sec:.5f}"

    # === Add Creator Info ===
    creator = ET.SubElement(activity_elem, "Creator", {"xsi:type": "Device_t"})
    ET.SubElement(creator, "Name").text = activity["source"]["name"]
    ET.SubElement(creator, "UnitId").text = "0"
    ET.SubElement(creator, "ProductID").text = "0"

    # === Write TCX Output ===
    tree = ET.ElementTree(tcx)
    tree.write(OUTPUT_FILE, encoding="UTF-8", xml_declaration=True)
    print(f"\n✅ TCX file written to: {os.path.abspath(OUTPUT_FILE)}")
