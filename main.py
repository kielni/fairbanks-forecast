import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
import json
import os
from typing import Optional

import boto3
from dateutil import parser as date_parser
import requests
from jinja2 import Template

PREFIX = os.environ.get("PREFIX", "fairbanks-test")
DATA_FILENAME = f"{PREFIX}/weather.json"
FORECAST_FILENAME = f"{PREFIX}/index.html"
HISTORY_FILENAME = f"{PREFIX}/history.html"


def debug() -> bool:
    return "t" in os.environ.get("WRITE_DEBUG", "").lower()


def download_forecast_history() -> dict:
    response = boto3.client("s3").get_object(
        Bucket=os.environ["S3_BUCKET"], Key=DATA_FILENAME
    )
    return json.loads(response["Body"].read())


def upload_forecast_history(data: dict):
    buf = BytesIO()
    buf.write(json.dumps(data, indent=2).encode("utf-8"))
    buf.seek(0)
    boto3.client("s3").upload_fileobj(buf, os.environ["S3_BUCKET"], DATA_FILENAME)
    print(f"uploaded forecasts to s3://{os.environ['S3_BUCKET']}/{DATA_FILENAME}")


def upload_html(text: str, key: str):
    boto3.client("s3").put_object(
        Body=text,
        Bucket=os.environ["S3_BUCKET"],
        Key=key,
        ACL="public-read",
        ContentType="text/html",
    )
    print(f"uploaded html to s3://{os.environ['S3_BUCKET']}/{key}")


def update_weather(weather: dict, get_current: bool = True):
    """Merge new weather data with current, then re-upload."""
    if get_current:
        current = download_forecast_history()
    else:
        current = {"days": {}, "nights": {}}
    # replace day-level data with the latest forecast
    for day in weather["days"]:
        # print(f"{day} = {weather['days'][day]}")
        current["days"].setdefault(day, {})
        current["days"][day].update(weather["days"][day])
    # prepend hour level forecasts
    for hour in weather["nights"]:
        current["nights"].setdefault(hour, [])
        current["nights"][hour] = weather["nights"][hour] + current["nights"][hour]
    print("merged existing data with new")
    upload_forecast_history(current)
    if debug():
        with open("latest.json", "w") as f:
            f.write(json.dumps(current, indent=2))
    return current


def parse_visual_crossing_forecast(
    vc_data: dict, as_of_dt: Optional[datetime] = None
) -> dict:
    """
    "days": [
        {
            "datetime": "2022-01-27",
            "description": "Becoming cloudy in the afternoon.",
            "hours": [
                {
                    "datetime": "00:00:00",
                    "cloudcover": 90.3,
                    "conditions": "Overcast",
    """
    data: dict = {"days": {}, "nights": {}}
    day_keys = ["moonphase", "sunrise", "sunset", "tempmax", "tempmin", "description"]
    hour_keys = ["cloudcover", "conditions", "temp", "icon"]
    as_of = (as_of_dt if as_of_dt else datetime.now()).isoformat()
    for day in vc_data["days"]:
        dt = date_parser.parse(day["datetime"])
        dt_str = dt.strftime("%Y-%m-%d")
        data["days"][dt_str] = {}
        for key in day_keys:
            data["days"][dt_str][key] = day.get(key)
        for hour in day["hours"]:
            ts = date_parser.parse(f"{day['datetime']} {hour['datetime']}")
            # skip unless 9pm-3am
            if 2 < ts.hour < 21:
                if ts.hour == 3:
                    print("\n")
                continue
            night = dt
            if ts.hour < 3:
                night = dt - timedelta(days=1)
            night_str = night.strftime("%Y-%m-%d")
            data["nights"].setdefault(night_str, [])
            fc = {"as_of": as_of, "hour": ts.strftime("%Y-%m-%d %H:%M")}
            for key in hour_keys:
                fc[key] = hour[key]
            data["nights"][night_str].append(fc)
            print(f"{fc['hour']}\t{fc['conditions']}\t{round(fc['cloudcover'])}%")
    """
    {
        "days": {
            "yyyy-mm-dd": {
                "moonphase": 0.86,
                "sunrise": "09:51:39",
                "sunset": "16:16:44",
                "tempmax": -5.7,
                "tempmin": -22.3
            }
        },
        "nights": {
            "yyyy-mm-ddTHH:MM:SS": [ # AK local time
                {
                    "hour": ""yyyy-mm-dd HH:mm",
                    "as_of": "yyyy-mm-dd HH:mm",  # forecast datetime
                    "cloudcover": 90.3,
                    "conditions": "Overcast",
                    "temp": -22.3,
                    "icon": "cloudy"
                }
            ]
        }
    }
    """
    return data


def get_visual_crossing_forecast(start_date: date, end_date: date) -> dict:
    # yyyy-mm-dd
    url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}/{start}/{end}"
    resp = requests.get(
        url.format(
            location="fairbanks%2C%20ak",
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
        ),
        params={
            "unitGroup": "us",
            "include": "hours",
            "key": os.environ["VC_KEY"],
            "contentType": "json",
        },
    )
    print("forecast status=", resp.status_code)
    return resp.json()


def sample_data():
    with open("weather.json") as f:
        return json.loads(f.read())


def moon_phase_class(phase: float) -> str:
    """
    https://www.visualcrossing.com/resources/documentation/weather-api/how-to-include-sunrise-sunset-and-moon-phase-data-into-your-api-requests/
    0 – new moon
    0-0.25 – waxing crescent
    0.25 – first quarter
    0.25-0.5 – waxing gibbous
    0.5 – full moon
    0.5-0.75 – waning gibbous
    0.75 – last quarter
    0.75 -1 – waning crescent
    1 - full moon
    """
    p = defaultdict(list)
    for idx in range(6):
        p["xc"].append(f"waxing-crescent-{idx+1}")
        p["xg"].append(f"waxing-gibbous-{idx+1}")
        p["ng"].append(f"waning-gibbous-{idx+1}")
        p["nc"].append(f"waning-crescent-{idx+1}")
    phases = (
        ["new"]
        + p["xc"]
        + ["first-quarter"]
        + p["xg"]
        + ["full"]
        + p["ng"]
        + ["third-quarter"]
        + p["nc"]
    )
    phase_idx = max(0, round(phase * 28) - 1)
    print(f"phase={phase} idx={phase_idx}")
    return f"wi wi-moon-{phases[phase_idx]}"


def render(data: dict):
    nights = {}
    for day in data["days"]:
        nights[day] = {
            "moon_icon": moon_phase_class(data["days"][day]["moonphase"]),
            "dt": date_parser.parse(day).date(),
        }
        print(f"phase={data['days'][day]['moonphase']} icon={nights[day]}")
    for night in data["nights"]:
        if night not in nights:
            forecast_dt = date_parser.parse(night).date()
            nights.setdefault(night, {"dt": forecast_dt})

        # group forecasts by as_of date
        by_as_of: dict = {}
        for fc in sorted(
            data["nights"][night], key=lambda hr: hr["as_of"].split("T"), reverse=True
        ):
            dt = date_parser.parse(fc["as_of"]).date()
            by_as_of.setdefault(dt, [])
            by_as_of[dt].append(fc)

        nights[night]["forecasts"] = []
        nights[night]["forecast_dt"] = []
        # most recently forecasted first
        for forecast_dt in sorted(by_as_of, reverse=True):
            clouds = [
                {
                    "as_of": date_parser.parse(hour["as_of"]),
                    "hour": date_parser.parse(hour["hour"]).strftime("%-I%p").lower(),
                    "cloud_cover": round(hour["cloudcover"]),
                    "cloud_class": f"clouds-{int(hour['cloudcover'] / 20)}",
                    "temp": int(hour["temp"]),
                }
                for hour in sorted(by_as_of[forecast_dt], key=lambda hr: hr["hour"])
            ]
            nights[night]["forecasts"].append(clouds)
            nights[night]["forecast_dt"].append(forecast_dt)

            if len(nights[night]["forecasts"]) >= 4:
                break

    if debug():
        with open("render.json", "w") as f:
            f.write(
                json.dumps(
                    [nights[dt] for dt in sorted(nights.keys())], indent=2, default=str
                )
            )

    today_str = date.today().strftime("%Y-%m-%d")
    print(f"{len(nights)} nights: {nights.keys()}")
    with open("index.jinja2") as f:
        template = Template(f.read())
    # future forecast
    sorted_nights = [nights[dt] for dt in sorted(nights.keys()) if dt > today_str]
    print(f"future: {len(sorted_nights)} days")
    print(sorted_nights[0])
    rendered = template.render(nights=sorted_nights)
    if debug():
        with open("index.html", "w") as f:
            print("render: wrote index.html")
            f.write(rendered)
    upload_html(rendered, FORECAST_FILENAME)

    # historical forecast
    sorted_nights = [nights[dt] for dt in sorted(nights.keys()) if dt <= today_str]
    if not sorted_nights:
        return
    print(f"history: {len(sorted_nights)} days")
    print(sorted_nights[0])
    rendered = template.render(nights=sorted_nights)
    if debug():
        with open("history.html", "w") as f:
            print("render: wrote history.html")
            f.write(rendered)
    upload_html(rendered, HISTORY_FILENAME)


def restart():
    # start fresh
    today = datetime.today()
    vc_data = sample_data()  # 2022-01-19 forecast
    with open(f"vc-{today.strftime('%Y-%m-%d')}.json", "w") as f:
        f.write(json.dumps(vc_data, indent=2))
    weather = parse_visual_crossing_forecast(vc_data, as_of_dt=datetime(2022, 1, 19))
    weather = update_weather(weather, get_current=False)
    print("as of 2022-01-19")

    vc_data = get_visual_crossing_forecast(
        today + timedelta(days=3), today + timedelta(days=10)
    )
    weather = parse_visual_crossing_forecast(vc_data)
    weather = update_weather(weather)
    render(weather)


def handler(event, context):
    """Lambda entry point"""
    today = date.today()
    vc_data = get_visual_crossing_forecast(
        today + timedelta(days=1), today + timedelta(days=10)
    )
    weather = parse_visual_crossing_forecast(vc_data)
    weather = update_weather(weather)
    render(weather)


def main(update: bool):
    today = date.today()
    if update:
        vc_data = get_visual_crossing_forecast(
            today + timedelta(days=1), today + timedelta(days=10)
        )
        weather = parse_visual_crossing_forecast(vc_data)
        weather = update_weather(weather)
    else:
        weather = download_forecast_history()
    render(weather)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", help="get new forecast", action="store_true")
    args = parser.parse_args()
    main(args.update)
