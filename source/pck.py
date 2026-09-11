"""Read the owned game's Godot 4 resource pack without running game scripts.

Format reference: Godot 4.6 core/io/file_access_pack.cpp and
file_access_encrypted.cpp (MIT). Keys remain in memory, never in reports.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct

from Crypto.Cipher import AES
import pefile

ROOT = Path(__file__).resolve().parents[1]


class Pack:
    def __init__(self, game: Path, path: Path | None = None, key: bytes | None = None):
        self.path = path or game / "eslabong.pck"
        self.stream = self.path.open("rb")
        header = self.stream.read(40)
        magic, version, major, minor, patch, flags, self.base, directory = struct.unpack("<6I2Q", header)
        assert magic == 0x43504447 and version == 3
        self.flags = flags
        self.directory_offset = directory
        self.stream.seek(directory)
        self.count = struct.unpack("<I", self.stream.read(4))[0]
        self.key = None
        if flags & 1:
            md5 = self.stream.read(16)
            length = struct.unpack("<Q", self.stream.read(8))[0]
            iv = self.stream.read(16)
            cipher = self.stream.read((length + 15) & ~15)
            if key is None:
                self.key, contents = self.find_key(game / "eslabong.exe", cipher, iv, length, md5)
            else:
                self.key = key
                contents = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(cipher)[:length]
                assert hashlib.md5(contents).digest() == md5
            self.directory_plain = contents
            source = io.BytesIO(contents)
        else:
            self.directory_plain = self.stream.read()
            source = io.BytesIO(self.directory_plain)
        self.files = {}
        self.entry_positions = {}
        for _ in range(self.count):
            length = struct.unpack("<I", source.read(4))[0]
            assert 0 < length < 16384
            name = source.read(length).rstrip(b"\0").decode("utf-8").removeprefix("res://")
            self.entry_positions[name] = source.tell()
            offset, size = struct.unpack("<2Q", source.read(16))
            digest = source.read(16).hex()
            bits = struct.unpack("<I", source.read(4))[0]
            assert name not in self.files
            self.files[name] = dict(offset=self.base + offset, size=size, md5=digest, flags=bits)

    @staticmethod
    def find_key(executable, cipher, iv, length, md5):
        binary = executable.read_bytes()
        pe = pefile.PE(data=binary, fast_load=True)
        for alignment in (16, 4, 1):
            for section_name in (b".data", b".rdata"):
                section = next(section for section in pe.sections if section.Name.rstrip(b"\0") == section_name)
                print(f"Inspecting resource key data: {section_name.decode()}, alignment {alignment}", flush=True)
                raw = section.get_data()
                for offset in range(0, len(raw) - 31, alignment):
                    if alignment == 4 and offset % 16 == 0 or alignment == 1 and offset % 4 == 0:
                        continue
                    key = raw[offset:offset + 32]
                    if len(set(key)) < 12:
                        continue
                    aes = AES.new(key, AES.MODE_ECB)
                    plain = bytes(a ^ b for a, b in zip(aes.encrypt(iv), cipher[:16]))
                    name_length = struct.unpack_from("<I", plain)[0]
                    if not 4 <= name_length <= 1024 or any(byte < 32 or byte > 126 for byte in plain[4:12]):
                        continue
                    data = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(cipher)[:length]
                    if hashlib.md5(data).digest() == md5:
                        print("Verified resource directory integrity.", flush=True)
                        return key, data
        raise ValueError("Resource directory could not be read")

    def read(self, name):
        entry = self.files[name]
        self.stream.seek(entry["offset"])
        if entry["flags"] & 1:
            digest = self.stream.read(16)
            length = struct.unpack("<Q", self.stream.read(8))[0]
            iv = self.stream.read(16)
            data = AES.new(self.key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(self.stream.read((length + 15) & ~15))[:length]
            assert hashlib.md5(data).digest() == digest
        else:
            data = self.stream.read(entry["size"])
        assert len(data) == entry["size"] and hashlib.md5(data).hexdigest() == entry["md5"], name
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, default=Path(r"H:\Games\Eslabong"))
    args = parser.parse_args()
    pack = Pack(args.game)
    out = ROOT / "work"
    out.mkdir(exist_ok=True)
    (out / "resource-index.json").write_text(json.dumps(pack.files, ensure_ascii=False, indent=2), encoding="utf-8")
    selected = []
    for name in pack.files:
        if re.search(r"translat|localiz|i18n|\.(csv|po|pot|json|gd|gdc)$|project\.(godot|binary)$", name, re.I):
            destination = out / "extracted" / name
            assert destination.resolve().is_relative_to((out / "extracted").resolve())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(pack.read(name))
            selected.append(name)
    (out / "selected-files.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Indexed {len(pack.files)} resources, extracted {len(selected)} candidates.", flush=True)


if __name__ == "__main__":
    main()
