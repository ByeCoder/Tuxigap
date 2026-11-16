#!/usr/bin/env python3
"""Check catalog placeholders and report honest translation coverage."""

from tuxigap.i18n import LANGUAGES, catalog, validate_catalogs


def main():
    errors = validate_catalogs()
    base = catalog("en")
    for code, name in LANGUAGES.items():
        translated = len(catalog(code))
        print(f"{code:2} {name:14} {translated:3}/{len(base)} keys; missing keys use English")
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("Catalog placeholders look good. Thanks for keeping translations safe!")


if __name__ == "__main__":
    main()
