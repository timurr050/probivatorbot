"""Генерирует реальные тест-файлы: JPG с EXIF/GPS и MP4 с метаданными."""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(tempfile.gettempdir()) / "probivbot_tests"
OUT.mkdir(exist_ok=True)


def make_jpg() -> Path:
    """JPG с EXIF: модель камеры, дата, GPS (Минск: 53.9, 27.5667)."""
    try:
        import piexif  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "piexif"])
        import piexif  # noqa: F401

    from PIL import Image

    img = Image.new("RGB", (640, 480), (120, 80, 40))
    img.save(str(OUT / "test_photo.jpg"), quality=95)

    lat = 53.9
    lng = 27.5667

    def dms(dec):  # -> [(num,den),(num,den),(num,den)]
        deg = int(abs(dec))
        rest = abs(dec) - deg
        minutes = int(rest * 60)
        seconds = int(round((rest * 60 - minutes) * 60 * 100))
        return [(deg, 1), (minutes, 1), (seconds, 1)] if seconds == 0 else [(deg, 1), (minutes, 1), (seconds, 100)]

    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: "Canon",
            piexif.ImageIFD.Model: "Canon EOS 5D Mark IV",
            piexif.ImageIFD.Software: "ProbiCam 1.0",
            piexif.ImageIFD.DateTime: "2024:05:17 14:30:00",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: "2024:05:17 14:30:00",
            piexif.ExifIFD.LensModel: "EF24-70mm f/2.8L II USM",
            piexif.ExifIFD.ExposureTime: (1, 250),
            piexif.ExifIFD.FNumber: (28, 10),
            piexif.ExifIFD.ISOSpeedRatings: 200,
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: dms(lng),
        },
    }
    piexif.insert(piexif.dump(exif_dict), str(OUT / "test_photo.jpg"))
    return OUT / "test_photo.jpg"


def make_mp4() -> Path:
    """MP4 с атомами ilst: ©mak/©mod/©day/©xyz(GPS) + mvhd/mdhd."""
    def atom(t, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + t + payload

    def item(tag: bytes, text: str) -> bytes:
        payload = b"data" + struct.pack(">II", 1, 0) + text.encode()
        data_atom = struct.pack(">I", 8 + len(payload)) + payload
        return atom(tag, data_atom)

    def ilst(*items) -> bytes:
        return atom(b"ilst", b"".join(items))

    def meta(*items) -> bytes:
        return atom(b"meta", b"\x00\x00\x00\x00" + b"".join(items))

    def udta(*items) -> bytes:
        return atom(b"udta", b"".join(items))

    import datetime as _dt
    epoch1904 = _dt.datetime(1904, 1, 1)
    created = int((_dt.datetime(2024, 6, 1, 12, 0, 0) - epoch1904).total_seconds())
    mvhd = atom(b"mvhd", struct.pack(">IIIIIIIIIIIIIIIIII",
                                     created, created, 0, 1000, 15000, 0x01000000,
                                     0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    mdhd = atom(b"mdhd", struct.pack(">IIIIH", 0, 0, 1000, 15000, 0x55C4))
    moov = atom(b"moov", mvhd + mdhd + meta(ilst(
        item(b"\xa9mak", "Apple"),
        item(b"\xa9mod", "iPhone 15 Pro"),
        item(b"\xa9day", "2024-06-01T12:00:00+03:00"),
        item(b"\xa9xyz", "+53.9000+027.5667/"),
    )))
    ftyp = atom(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41")
    target = OUT / "test_video.mp4"
    target.write_bytes(ftyp + moov)
    return target


def main() -> None:
    jpg = make_jpg()
    mp4 = make_mp4()
    print(jpg)
    print(mp4)


if __name__ == "__main__":
    main()
