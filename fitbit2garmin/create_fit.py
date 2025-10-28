import json
import os
import statistics
from datetime import datetime, timezone


def create_fit(log_id: str):
    # Import builder / message classes from fit-tool
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.activity_message import ActivityMessage
    from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
    from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.profile_type import (
        DeviceIndex,
        FileType,
        GarminProduct,
        Manufacturer,
        Sport,
        SubSport,
    )

    # === CONFIG ===
    HEART_RATE_FILE = f"f2g/{log_id}/exercise-heart-rate.json"
    CALORIES_FILE = f"f2g/{log_id}/exercise-calories.json"
    ACTIVITY_FILE = f"f2g/{log_id}/exercise-activity.json"
    OUTPUT_FILE = f"f2g/exercise-{log_id}.fit"

    # Mapping Fitbit → FIT tool sport enum
    FITBIT_TO_FIT_TOOL_SPORT = {
        "Run": Sport.RUNNING,
        "Walk": Sport.WALKING,
        "Walking": Sport.WALKING,
        "Hike": Sport.HIKING,
        "Bike": Sport.CYCLING,
        "Biking": Sport.CYCLING,
        "Outdoor Bike": Sport.CYCLING,
        "Treadmill": Sport.RUNNING,
        "Elliptical": Sport.FITNESS_EQUIPMENT,
        "Swim": Sport.SWIMMING,
        "Strength Training": Sport.FITNESS_EQUIPMENT,
        "Workout": Sport.FITNESS_EQUIPMENT,
        "Weights": Sport.FITNESS_EQUIPMENT,
        "Aerobic Workout": Sport.SOCCER,
        "Sport": Sport.SOCCER,
        # Add more as needed
    }

    # Activities where distance is relevant
    DISTANCE_RELEVANT = {
        "Run",
        "Walk",
        "Walking",
        "Hike",
        "Bike",
        "Biking",
        "Outdoor Bike",
        "Treadmill",
        "Swim",
        "Swimming",
        "Sport",
        "Elliptical",
        "Aerobic Workout",
    }

    # Activities where elevation gain is relevant
    ELEVATION_RELEVANT = {
        "Run",
        "Walk",
        "Walking",
        "Hike",
        "Bike",
        "Biking",
        "Outdoor Bike",
        "Treadmill",
        "Elliptical",
        "Hiking",
        "Running",
        "Cycling",
        "Aerobic Workout",
        "Sport",
    }

    DEFAULT_STRIDE_LENGTH_M = 0.762

    # Load data
    with open(HEART_RATE_FILE) as f:
        hr_data = json.load(f)

    calorie_data = None
    calories_available = False
    try:
        with open(CALORIES_FILE) as f:
            calorie_data = json.load(f)
            calories_available = True
    except FileNotFoundError:
        print("⚠️ Calories file not found — skipping per-minute calories")

    with open(ACTIVITY_FILE) as f:
        activity = json.load(f)

    # Parse metadata
    start_time_str = activity["startTime"]
    start_time = datetime.fromisoformat(start_time_str)  # timezone-aware
    start_time_utc = start_time.astimezone(timezone.utc)
    duration_s = activity["duration"] / 1000.0

    # Handle distance / steps fallback
    distance_km = activity.get("distance", 0.0)
    steps = activity.get("steps", 0)
    if distance_km == 0.0:
        if steps and activity.get("activityName") in DISTANCE_RELEVANT:
            distance_km = (steps * DEFAULT_STRIDE_LENGTH_M) / 1000.0
            print(f"ℹ Estimated distance from {steps} steps: {distance_km:.3f} km")
        else:
            print(
                f"⚠ No distance and no valid step estimation for '{activity.get('activityName')}'. Using 0 km."
            )
    distance_m = distance_km * 1000.0

    # Elevation gain
    elevation_gain = 0
    if activity.get("activityName") in ELEVATION_RELEVANT:
        elevation_gain = int(round(activity.get("elevationGain", 0.0)))

    calories_total = activity.get("calories", 0)

    fitbit_activity = activity.get("activityName", "Workout")
    fit_sport = FITBIT_TO_FIT_TOOL_SPORT.get(fitbit_activity, Sport.FITNESS_EQUIPMENT)

    # Parse heart rate data
    hr_times = []
    hr_values = []
    date_str = hr_data["activities-heart"][0]["dateTime"]
    tz_offset = start_time_str[-6:]  # e.g. "-07:00"

    for entry in hr_data["activities-heart-intraday"]["dataset"]:
        time_part = entry["time"]  # "HH:MM:SS"
        dt = datetime.fromisoformat(f"{date_str}T{time_part}{tz_offset}")
        hr_times.append(dt)
        hr_values.append(entry["value"])

    if not hr_values:
        raise RuntimeError("No heart rate data available")

    min_hr = min(hr_values)
    max_hr = max(hr_values)
    avg_hr = round(statistics.mean(hr_values))

    # Parse calorie intraday if available
    cal_map = {}
    if calories_available:
        try:
            base_date = calorie_data["activities-calories"][0]["dateTime"] # type: ignore[index]
            for entry in calorie_data["activities-calories-intraday"]["dataset"]: # type: ignore[index]
                t = entry["time"]
                dt = datetime.fromisoformat(f"{base_date}T{t}{tz_offset}")
                cal_map[dt.replace(second=0, microsecond=0)] = entry["value"]
        except Exception as e:
            print("⚠ Could not parse calorie intraday:", e)
            cal_map = {}
            calories_available = False

    # === Build FIT file ===
    builder = FitFileBuilder(auto_define=True)

    # File ID message
    fid = FileIdMessage()
    fid.time_created = round(start_time_utc.timestamp() * 1000)
    fid.manufacturer = Manufacturer.GARMIN.value
    fid.product = 65534
    fid.type = FileType.ACTIVITY
    fid.garmin_product = GarminProduct.CONNECT.value
    builder.add(fid)

    # File creator message
    fcm = FileCreatorMessage()
    fcm.software_version = 320
    builder.add(fcm)

    # Device info message
    dim = DeviceInfoMessage()
    dim.timestamp = round(start_time_utc.timestamp() * 1000)
    dim.manufacturer = Manufacturer.GARMIN.value
    dim.product = 65534
    dim.device_index = DeviceIndex.CREATOR.value
    dim.device_type = 21
    dim.garmin_product = GarminProduct.CONNECT.value
    builder.add(dim)

    # Lap message
    lap = LapMessage()
    lap.timestamp = round(start_time_utc.timestamp() * 1000)
    lap.start_time = round(start_time_utc.timestamp() * 1000)
    lap.message_index = 0
    lap.total_elapsed_time = duration_s
    lap.total_timer_time = duration_s
    lap.total_moving_time = duration_s
    lap.total_distance = distance_m
    lap.total_calories = calories_total
    lap.average_heart_rate = avg_hr # type: ignore[attr-defined]
    lap.maximum_heart_rate = max_hr # type: ignore[attr-defined]
    lap.min_heart_rate = min_hr
    lap.avg_speed = distance_m / duration_s
    lap.enhanced_avg_speed = distance_m / duration_s
    lap.total_ascent = elevation_gain
    lap.sport = fit_sport
    if fitbit_activity == "Weights":
        lap.sub_sport = SubSport.STRENGTH_TRAINING
    elif fitbit_activity == "Elliptical":
        lap.sub_sport = SubSport.ELLIPTICAL
    builder.add(lap)

    # Session message
    sess = SessionMessage()
    sess.start_time = round(start_time_utc.timestamp() * 1000)
    sess.message_index = 0
    sess.total_elapsed_time = duration_s
    sess.total_timer_time = duration_s
    sess.total_moving_time = duration_s
    sess.total_distance = distance_m
    sess.total_calories = calories_total
    sess.average_heart_rate = avg_hr # type: ignore[attr-defined]
    sess.maximum_heart_rate = max_hr # type: ignore[attr-defined]
    sess.min_heart_rate = min_hr
    sess.avg_speed = distance_m / duration_s
    sess.enhanced_avg_speed = distance_m / duration_s
    sess.total_ascent = elevation_gain
    sess.sport = fit_sport
    sess.num_laps = 1
    if fitbit_activity == "Weights":
        sess.sub_sport = SubSport.STRENGTH_TRAINING
    elif fitbit_activity == "Elliptical":
        sess.sub_sport = SubSport.ELLIPTICAL
    builder.add(sess)

    # Activity message
    ac = ActivityMessage()
    ac.timestamp = round(start_time_utc.timestamp() * 1000)
    ac.num_sessions = 1
    ac.total_timer_time = duration_s
    builder.add(ac)

    # Record messages
    for dt, hr in zip(hr_times, hr_values):
        rec = RecordMessage()
        rec.timestamp = round(dt.astimezone(timezone.utc).timestamp() * 1000)
        rec.heart_rate = hr
        if calories_available:
            ck = dt.replace(second=0, microsecond=0)
            cal_min = cal_map.get(ck)
            if cal_min is not None:
                rec.calories = cal_min / 60.0
        builder.add(rec)

    # Build FIT file object and save
    fit_file_obj = builder.build()
    fit_file_obj.to_file(OUTPUT_FILE)

    print("✅ FIT file written:", os.path.abspath(OUTPUT_FILE))
