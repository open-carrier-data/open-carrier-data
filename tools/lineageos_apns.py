"""The schema rules of LineageOS's android_vendor_apn.

A LineageOS build checks its merged apns-conf.xml against the repository's
apns-conf.xsd, and a device that ships generated/android/apns-conf.xml through
LineageOS's prebuilt_etc_xml module is checked the same way.
fits_lineageos_schema mirrors the rules of that schema the profile schema does
not already enforce, so the generator can leave out a row the build would
reject.
"""

from __future__ import annotations

import re
from typing import Any


# apns-conf.xsd at LineageOS android_vendor_apn 6e73ba90 types mmsc, proxy and
# server as xs:anyURI. libxml2, which checks the schema during the build,
# rejects a value whose text before the first colon is not a URI scheme, such as
# "10.0.0.1:8080", a bad percent escape, a second "#", a second "@" in the
# authority, or a port that is empty or not a number.
URI_ATTRIBUTES = ("mmsc", "proxy", "server")
URI_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
BAD_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
URI_DELIMITER_RE = re.compile(r"[/?#]")
NUMBER_BITMASK_RE = re.compile(r"\d+(\|\d+)*")
INFRASTRUCTURE_BITMASK_RE = re.compile(r"(cellular|satellite)(\|(cellular|satellite))*")
INTEGER_RANGES = {"authtype": (0, 3), "skip_464xlat": (0, 1)}


def schema_uri_ok(value: str) -> bool:
    if BAD_PERCENT_RE.search(value) or value.count("#") > 1:
        return False
    rest = value
    if ":" in URI_DELIMITER_RE.split(value, maxsplit=1)[0]:
        scheme, _, rest = value.partition(":")
        if not URI_SCHEME_RE.fullmatch(scheme):
            return False
    if not rest.startswith("//"):
        return True
    authority = URI_DELIMITER_RE.split(rest[2:], maxsplit=1)[0]
    userinfo, _, hostport = authority.rpartition("@")
    if "@" in userinfo:
        return False
    if hostport.startswith("["):
        _, bracket, port = hostport.partition("]")
        if not bracket:
            return False
    else:
        port = hostport[hostport.find(":"):] if ":" in hostport else ""
    return not port or (port[0] == ":" and port[1:].isdigit())


def fits_lineageos_schema(record: dict[str, Any]) -> bool:
    """Whether LineageOS's apns-conf.xsd accepts this APN XML row. Only the
    rules the profile schema leaves open are checked: URIs, the narrower ranges
    of authtype and skip_464xlat, and the bitmask patterns."""
    for key in URI_ATTRIBUTES:
        if key in record and not schema_uri_ok(str(record[key])):
            return False
    for key, (low, high) in INTEGER_RANGES.items():
        if key not in record:
            continue
        try:
            value = int(record[key])
        except (TypeError, ValueError):
            return False
        if not low <= value <= high:
            return False
    for key in ("bearer_bitmask", "network_type_bitmask", "lingering_network_type_bitmask"):
        if key in record and not NUMBER_BITMASK_RE.fullmatch(str(record[key])):
            return False
    if "infrastructure_bitmask" in record and not INFRASTRUCTURE_BITMASK_RE.fullmatch(
        str(record["infrastructure_bitmask"])
    ):
        return False
    return True
