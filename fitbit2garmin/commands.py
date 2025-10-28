import asyncio
import functools
import json
import logging
import os
import pathlib

from collections.abc import Callable, Coroutine
from datetime import date, datetime
from typing import Any

import aiohttp

from dateutil.relativedelta import relativedelta
from dateutil.rrule import MONTHLY, rrule

from . import aiohttp_fitbit_api, create_fit, create_tcx


def run_aiohttp_fitbit_api_call(
    name: str,
    auth_file_path: pathlib.Path,
    func: Callable[..., Coroutine[Any, Any, Any]],
    *,
    raise_for_status: bool = True,
):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with aiohttp.ClientSession(raise_for_status=raise_for_status) as session:
            while True:
                try:
                    logging.debug(f"{name}: Authorizing request.")
                    if auth_file_path.exists():
                        with auth_file_path.open("r") as fr:
                            authorization = json.loads(fr.read())
                    else:
                        authorization = None
                    authorization = await aiohttp_fitbit_api.execute_oauth2_flow(
                        session, authorization
                    )
                    with auth_file_path.open("w") as fw:
                        print(json.dumps(authorization), file=fw)
                    bearer_token = authorization["access_token"]
                    logging.debug(f"{name}: Sending request.")
                    result = await func(session, bearer_token, *args, **kwargs)
                except aiohttp.ClientResponseError as err:
                    logging.error(f"{name}: Request failed: {err}")
                    continue
                except asyncio.TimeoutError:
                    logging.error(f"{name}: Request timed out.")
                    continue
                logging.debug(f"{name}: Done.")
                return result

    return wrapper


async def create_activity_tcx_or_fit(
    cache_directory: pathlib.Path,
    tcxs_directory: pathlib.Path,
    start_date: date,
    end_date: date,
    is_tcx: bool,
):
    cache_directory.mkdir(parents=True, exist_ok=True)
    tcxs_directory.mkdir(parents=True, exist_ok=True)

    auth_file_name = ".auth"
    auth_file_path = cache_directory / auth_file_name

    # Fetch activity log.
    date_range = f"{start_date}-{end_date}"
    activity_log_file_path = cache_directory / f".exercises.{date_range}.jsonl"
    activity_log_done_file_path = cache_directory / f".exercises.{date_range}"
    if not activity_log_file_path.exists() or not activity_log_done_file_path.exists():
        get_activity_log_list = run_aiohttp_fitbit_api_call(
            "activity-log-list",
            auth_file_path,
            aiohttp_fitbit_api.get_activity_log_list,
        )
        logging.info("Fetching activity log list.")
        activities = await get_activity_log_list(start_date, end_date)
        with activity_log_file_path.open("w") as fw:
            for activity in activities:
                print(json.dumps(activity), file=fw)
        activity_log_done_file_path.touch()
        logging.info("Activity log list fetched.")

    # Count number of activities.
    with activity_log_file_path.open("r") as fr:
        num_activities = sum(1 for _ in fr)

    # Fetch tcx for each activity.
    with activity_log_file_path.open("r") as fr:
        for i, activity in enumerate(map(json.loads, fr)):
            activity_number = i + 1
            progress = f"[{activity_number}/{num_activities}]"
            log_id = activity["logId"]
            if not os.path.isdir(f"{tcxs_directory}/{log_id}"):
                os.mkdir(f"{tcxs_directory}/{log_id}")

            logging.info(f"{progress} Fetching activity {log_id}.")
            get_activity_tcx = run_aiohttp_fitbit_api_call(
                f"{progress} activity-tcx-{log_id}",
                auth_file_path,
                aiohttp_fitbit_api.get_activity_tcx,
            )
            tcx = await get_activity_tcx(log_id)
            heart_rate_url = activity.get("heartRateLink", "missing")

            # Create json file for activity
            activity_file_path = (
                tcxs_directory / f"{log_id}" / "exercise-activity.json"
            )
            if not activity_file_path.exists():
                with activity_file_path.open("w") as fw:
                    json.dump(activity, fw)

            if (
                activity["logType"] == "auto_detected" or tcx.count(b"\n") <= 15
            ) and heart_rate_url != "missing":
                logging.info(f"{progress} Heart rate url found: {heart_rate_url}")
                activity_heart_rate_file_path = (
                    tcxs_directory / f"{log_id}" / "exercise-heart-rate.json"
                )
                if not activity_heart_rate_file_path.exists():
                    get_activity_heart_rate = run_aiohttp_fitbit_api_call(
                        f"{progress} activity-heart-rate-{log_id}",
                        auth_file_path,
                        aiohttp_fitbit_api.get_activity_heart_rate,
                    )
                    heart_rate = await get_activity_heart_rate(heart_rate_url)
                    # Create json file for activity heart rate
                    with activity_heart_rate_file_path.open("wb") as fw:
                        fw.write(heart_rate)

                calories_url = activity.get("caloriesLink", "missing")
                if calories_url != "missing":
                    logging.info(f"{progress} Calories url found: {calories_url}")
                    activity_calories_file_path = (
                        tcxs_directory / f"{log_id}" / "exercise-calories.json"
                    )
                    if not activity_calories_file_path.exists():
                        get_activity_calories = run_aiohttp_fitbit_api_call(
                            f"{progress} activity-calories-{log_id}",
                            auth_file_path,
                            aiohttp_fitbit_api.get_activity_calories,
                            raise_for_status=False
                        )
                        calories = await get_activity_calories(calories_url)
                        if calories != None:
                            # Create json file for activity heart rate
                            with activity_calories_file_path.open("wb") as fw:
                                fw.write(calories)

                if is_tcx:
                    create_tcx.create_tcx(log_id)
                else:
                    create_fit.create_fit(log_id)
            else:
                logging.info(f"{progress} Skipping exercise {log_id} for {activity["activityName"]}")
                input("Press Enter to continue...")
