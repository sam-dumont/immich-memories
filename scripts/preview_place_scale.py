#!/usr/bin/env python3
"""Capture production place captions/titles, then compare two revisions offline.

Use --capture DIR against each revision via PYTHONPATH, then --compare BEFORE AFTER
--output DIR. All locations and dates are synthetic; no library or network is used.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from immich_memories.analysis.place_names import PlaceNames
from immich_memories.analysis.trip_detection import detect_trips
from immich_memories.api.models import Asset, ExifInfo
from immich_memories.generate_captions import prepare_location_captions
from immich_memories.generate_privacy import clip_location_name
from immich_memories.processing.clip_caption import (
    caption_filters,
    caption_font_path,
    captions_for_timeline,
)
from immich_memories.processing.location_card_route import RouteStop, location_card_moves
from immich_memories.titles._trip_titles import generate_trip_title
from immich_memories.titles.renderer_pil import RenderSettings, TitleRenderer
from immich_memories.titles.styles import PRESET_STYLES

WIDTH, HEIGHT = 640, 360


def picture(index, lat, lon, city, region, country):
    taken = datetime(2030, 7, 1, 10, tzinfo=UTC) + timedelta(hours=6 * index)
    return Asset(
        id=f"synthetic-{index}",
        type="IMAGE",
        fileCreatedAt=taken,
        fileModifiedAt=taken,
        updatedAt=taken,
        exifInfo=ExifInfo(latitude=lat, longitude=lon, city=city, state=region, country=country),
    )


class FixtureGeocoder:
    """Replace only the external address lookup, with the same hierarchy on both revisions."""

    def address(self, lat, lon):
        district = {13.40: "Mitte", 13.42: "Kreuzberg", 13.30: "Charlottenburg"}[lon]
        return {"suburb": district, "city": "Berlin", "state": "Berlin", "country": "Germany"}


def title_frame(title=""):
    renderer = TitleRenderer(
        PRESET_STYLES["elegant_minimal"],
        RenderSettings(width=WIDTH, height=HEIGHT, animated_background=False),
    )
    return renderer.render_frame(title, frame_number=90)


def capture(folder):
    folder.mkdir(parents=True, exist_ok=True)
    background = folder / "background.png"
    title_frame().save(background)
    clips, stops = [], []
    for day, (district, lon) in enumerate(
        [("Mitte", 13.40), ("Kreuzberg", 13.42), ("Charlottenburg", 13.30)], 1
    ):
        asset = picture(day, 52.52, lon, district, "Berlin", "Germany")
        PlaceNames(FixtureGeocoder()).name([asset])
        name = clip_location_name(asset.exif_info)
        clips.append(SimpleNamespace(location_name=name, date=f"2030-07-0{day}"))
        stops.append(RouteStop(52.52, lon, name, date(2030, 7, day)))
    # The old route function also took home; the fixture has no home suppression here.
    route_args = (
        {"home": None} if "home" in inspect.signature(location_card_moves).parameters else {}
    )
    moves = location_card_moves(stops, limit=None, **route_args)
    captions = captions_for_timeline(clips, place=True)
    record = {
        "berlin": [
            {"place": c.place, "date": c.date, "card": m is not None}
            for c, m in zip(captions, moves, strict=True)
        ]
    }
    for day, caption in enumerate(captions, 1):
        filters = caption_filters(caption, WIDTH, HEIGHT, font_path=caption_font_path())
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(background),
                "-vf",
                ",".join(filters),
                "-frames:v",
                "1",
                "-update",
                "1",
                str(folder / f"berlin-{day}.png"),
            ],
            check=True,
        )
    from immich_memories.processing.assembly_config import AssemblyClip

    home = AssemblyClip(
        path=Path("synthetic.mp4"),
        duration=3,
        date="2030-07-04",
        latitude=50.843,
        longitude=4.362,
        location_name="Brussels, Belgium",
    )
    params = SimpleNamespace(
        add_place_overlay=True,
        privacy_mode=False,
        client=None,
        config=SimpleNamespace(
            title_screens=SimpleNamespace(locale="en"),
            trips=SimpleNamespace(homebase_latitude=50.843, homebase_longitude=4.362),
        ),
    )
    caption = captions_for_timeline(prepare_location_captions(params, [home]), place=True)[0]
    record["home"] = caption.place
    filters = caption_filters(caption, WIDTH, HEIGHT, font_path=caption_font_path())
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(background),
            "-vf",
            ",".join(filters),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(folder / "home.png"),
        ],
        check=True,
    )
    record["road_trip"] = []
    for count in (10, 11):
        assets = []
        for number, lat, lon, city, region in [
            (count, 36.17, -115.14, "Las Vegas", "Nevada"),
            (4, 37.20, -112.99, "Springdale", "Utah"),
            (3, 36.86, -111.46, "Page", "Arizona"),
            (3, 34.05, -118.24, "Los Angeles", "California"),
        ]:
            for _ in range(number):
                assets.append(picture(len(assets), lat, lon, city, region, "United States"))
        (trip,) = detect_trips(assets, 64, -150)
        title = generate_trip_title(
            trip.location_name,
            date(2030, 7, 1),
            date(2030, 7, 6),
            locale="en",
            kind=trip.location_kind,
        )
        record["road_trip"].append(
            {"city_photos": count, "place": trip.location_name, "title": title}
        )
        title_frame(title).save(folder / f"road-{count}.png")
    (folder / "behavior.json").write_text(json.dumps(record, indent=2) + "\n")


def comparison(before, after, stem, heading, notes):
    image = Image.new("RGB", (1328, 526), "#10191d")
    draw = ImageDraw.Draw(image)

    def font(size):
        return ImageFont.truetype(caption_font_path(), size)

    draw.text((24, 18), heading, font=font(26), fill="#ffffff")
    for index, (folder, label, colour) in enumerate(
        [(before, "BEFORE / MAIN", "#f0b899"), (after, "AFTER / THIS FIX", "#99d8c0")]
    ):
        x = 16 + index * 656
        draw.text((x + 8, 62), label, font=font(18), fill=colour)
        with Image.open(folder / f"{stem}.png") as frame:
            image.paste(frame, (x, 96))
        draw.text((x + 8, 465), notes[index], font=font(16), fill=colour)
    draw.text(
        (24, 502),
        "Synthetic fixtures · production caption/title renderers · no personal photos",
        font=font(13),
        fill="#a2adb1",
    )
    return image


def compare(before, after, output):
    output.mkdir(parents=True, exist_ok=True)
    evidence = {
        name: json.loads((folder / "behavior.json").read_text())
        for name, folder in [("before", before), ("after", after)]
    }
    frames = []
    for day, district in enumerate(["Mitte", "Kreuzberg", "Charlottenburg"], 1):
        notes = []
        for revision in ("before", "after"):
            row = evidence[revision]["berlin"][day - 1]
            notes.append(
                "New district label and location card"
                if row["card"]
                else "Berlin unchanged; no extra label"
                if day > 1
                else "First place caption"
            )
        frame = comparison(
            before, after, f"berlin-{day}", f"Berlin stay · day {day} · {district}", notes
        )
        frames.append(frame)
        frame.save(output / f"berlin-day-{day}.png", optimize=True)
    for stem, heading, notes in [
        (
            "home",
            "Returning home · known city stays visible",
            ("Home label hidden", "Brussels shown; repeats deduplicate"),
        ),
        (
            "road-11",
            "Four-state road trip · one extra Las Vegas photo",
            ("United States becomes Las Vegas", "United States stays United States"),
        ),
    ]:
        frame = comparison(before, after, stem, heading, notes)
        frames.append(frame)
        frame.save(output / f"{stem}.png", optimize=True)
    frames[0].save(
        output / "demo.webp",
        save_all=True,
        append_images=frames[1:],
        duration=2500,
        loop=0,
        lossless=True,
    )
    (output / "behavior.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", type=Path)
    mode.add_argument("--compare", type=Path, nargs=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.capture:
        capture(args.capture)
    elif args.output:
        compare(*args.compare, args.output)
    else:
        parser.error("--compare requires --output")
