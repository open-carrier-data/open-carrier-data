#!/usr/bin/env python3
"""The layout and the schema rules of LineageOS's android_vendor_apn.

The per-country export in generated/android/apns/ uses the layout of LineageOS's
android_vendor_apn repository: one file per country, named by the ISO 3166 code,
for example DE.xml. LineageOS split its list by MCC. Its split matches the
country Android's MccTable gives each MCC, except for the five MCCs in
LINEAGEOS_SPLIT. This module repeats that split, so the files can replace the
ones in a LineageOS tree. A LineageOS build checks the merged file against the
repository's apns-conf.xsd, so fits_lineageos_schema mirrors the rules of that
schema the profile schema does not already enforce.
"""

from __future__ import annotations

import re
from typing import Any

# Android's MccTable (frameworks/opt/telephony, MccTable.java), which lists the
# ITU E.212 MCC assignments with their ISO 3166 codes, uppercased here.
ANDROID_MCC_COUNTRIES = {
    "202": "GR", "204": "NL", "206": "BE", "208": "FR", "212": "MC", "213": "AD", "214": "ES",
    "216": "HU", "218": "BA", "219": "HR", "220": "RS", "221": "XK", "222": "IT", "225": "VA",
    "226": "RO", "228": "CH", "230": "CZ", "231": "SK", "232": "AT", "234": "GB", "235": "GB",
    "238": "DK", "240": "SE", "242": "NO", "244": "FI", "246": "LT", "247": "LV", "248": "EE",
    "250": "RU", "255": "UA", "257": "BY", "259": "MD", "260": "PL", "262": "DE", "266": "GI",
    "268": "PT", "270": "LU", "272": "IE", "274": "IS", "276": "AL", "278": "MT", "280": "CY",
    "282": "GE", "283": "AM", "284": "BG", "286": "TR", "288": "FO", "289": "GE", "290": "GL",
    "292": "SM", "293": "SI", "294": "MK", "295": "LI", "297": "ME", "302": "CA", "308": "PM",
    "310": "US", "311": "US", "312": "US", "313": "US", "314": "US", "315": "US", "316": "US",
    "330": "PR", "332": "VI", "334": "MX", "338": "JM", "340": "GP", "342": "BB", "344": "AG",
    "346": "KY", "348": "VG", "350": "BM", "352": "GD", "354": "MS", "356": "KN", "358": "LC",
    "360": "VC", "362": "CW", "363": "AW", "364": "BS", "365": "AI", "366": "DM", "368": "CU",
    "370": "DO", "372": "HT", "374": "TT", "376": "TC", "400": "AZ", "401": "KZ", "402": "BT",
    "404": "IN", "405": "IN", "406": "IN", "410": "PK", "412": "AF", "413": "LK", "414": "MM",
    "415": "LB", "416": "JO", "417": "SY", "418": "IQ", "419": "KW", "420": "SA", "421": "YE",
    "422": "OM", "423": "PS", "424": "AE", "425": "IL", "426": "BH", "427": "QA", "428": "MN",
    "429": "NP", "430": "AE", "431": "AE", "432": "IR", "434": "UZ", "436": "TJ", "437": "KG",
    "438": "TM", "440": "JP", "441": "JP", "450": "KR", "452": "VN", "454": "HK", "455": "MO",
    "456": "KH", "457": "LA", "460": "CN", "461": "CN", "466": "TW", "467": "KP", "470": "BD",
    "472": "MV", "502": "MY", "505": "AU", "510": "ID", "514": "TL", "515": "PH", "520": "TH",
    "525": "SG", "528": "BN", "530": "NZ", "534": "MP", "535": "GU", "536": "NR", "537": "PG",
    "539": "TO", "540": "SB", "541": "VU", "542": "FJ", "543": "WF", "544": "AS", "545": "KI",
    "546": "NC", "547": "PF", "548": "CK", "549": "WS", "550": "FM", "551": "MH", "552": "PW",
    "553": "TV", "554": "TK", "555": "NU", "602": "EG", "603": "DZ", "604": "MA", "605": "TN",
    "606": "LY", "607": "GM", "608": "SN", "609": "MR", "610": "ML", "611": "GN", "612": "CI",
    "613": "BF", "614": "NE", "615": "TG", "616": "BJ", "617": "MU", "618": "LR", "619": "SL",
    "620": "GH", "621": "NG", "622": "TD", "623": "CF", "624": "CM", "625": "CV", "626": "ST",
    "627": "GQ", "628": "GA", "629": "CG", "630": "CD", "631": "AO", "632": "GW", "633": "SC",
    "634": "SD", "635": "RW", "636": "ET", "637": "SO", "638": "DJ", "639": "KE", "640": "TZ",
    "641": "UG", "642": "BI", "643": "MZ", "645": "ZM", "646": "MG", "647": "RE", "648": "ZW",
    "649": "NA", "650": "MW", "651": "LS", "652": "BW", "653": "SZ", "654": "KM", "655": "ZA",
    "657": "ER", "658": "SH", "659": "SS", "702": "BZ", "704": "GT", "706": "SV", "708": "HN",
    "710": "NI", "712": "CR", "714": "PA", "716": "PE", "722": "AR", "724": "BR", "730": "CL",
    "732": "CO", "734": "VE", "736": "BO", "738": "GY", "740": "EC", "742": "GF", "744": "PY",
    "746": "SR", "748": "UY", "750": "FK",
}

# LineageOS android_vendor_apn at 6e73ba90 (2026-09-23) splits these MCCs
# differently from MccTable. It repeats every row of MCC 425 in IL.xml and
# PS.xml and every row of MCC 647 in RE.xml and YT.xml, keeps MCC 340 in GF.xml
# and MCC 362 in AN.xml, and puts MCC 901 in INTL.xml.
LINEAGEOS_SPLIT = {
    "340": ("GF",),
    "362": ("AN",),
    "425": ("IL", "PS"),
    "647": ("RE", "YT"),
    "901": ("INTL",),
}

# MCC to the names of the files its rows belong to. An MCC that is missing here,
# such as 001 for test networks or 999 for internal use, has no country file.
MCC_COUNTRY_FILES: dict[str, tuple[str, ...]] = {
    **{mcc: (country,) for mcc, country in ANDROID_MCC_COUNTRIES.items()},
    **LINEAGEOS_SPLIT,
}

COUNTRY_FILE_NAMES = frozenset(
    f"{country}.xml" for countries in MCC_COUNTRY_FILES.values() for country in countries
)


def country_files(mcc: str) -> tuple[str, ...]:
    """The file names an APN row with this MCC belongs in, none when the MCC
    has no country."""
    return tuple(f"{country}.xml" for country in MCC_COUNTRY_FILES.get(mcc, ()))


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
