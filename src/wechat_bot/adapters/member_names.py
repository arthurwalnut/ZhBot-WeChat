"""Read nonfriend names using the already connected, fingerprint-checked helper.

Adapted from Prometheus-first/helper commit
7302da4721ee87199d7828a134a3d7ac846799d1, wxbot_framework/contacts.py.
SPDX-License-Identifier: LicenseRef-helper-noncommercial-1.0
See adjacent helper_names.LICENSE and helper_names.NOTICE, plus the project's
THIRD_PARTY_NOTICES.md.

Local changes: lazy imports from our pinned helper; require the bound account;
include 4.1.15.56 after a real read and independent user name confirmation on
2026-10-30. Upstream enables this LRU layout for 4.2.0.11. The caller must first
verify the full core fingerprint; this function does not discover or open a PID.
"""
from __future__ import annotations

import struct


def read_group_contact_name(read_memory, core_base, wxid, *, expected_account):
    from wxbot_framework.account import read_current_account, validate_account
    from wxbot_framework.contacts import ContactDirectoryError, _DirectoryReader, _directory_cache
    from wxbot_framework.group_members import _StableReader, _find_room
    from wxbot_framework.native_profiles import select_memory_profile

    validate_account(wxid)
    account = read_current_account(read_memory, core_base)
    if not account or account != expected_account:
        return None
    try:
        profile = select_memory_profile(read_memory, core_base)
        if profile is None or profile.version not in ('4.1.15.56', '4.2.0.11'):
            return None
        directory = _DirectoryReader(read_memory)
        _, cache = _directory_cache(directory, core_base, profile.rva)
        reader = _StableReader(read_memory)
        # _find_room uses +0x38, hence this LRU begins at ContactCache +0x108.
        contact = _find_room(reader, cache + 0xD0, wxid)
        if not contact or reader.string(contact + 8, 127, encoding='ascii') != wxid:
            return None
        name = reader.string(contact + 0xD8, 256, empty=True).strip()
        if not name or len(name) > 64 or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
            return None
        reader.verify()
        directory.verify()
        if read_current_account(read_memory, core_base) != account:
            return None
        return name
    except (OSError, ValueError, ContactDirectoryError, struct.error):
        return None
