"""Write tests/fixtures/bcf_schema_names.json: for each biber release named, the elements of
its own schema of the control file (data/schemata/bcf.rng in biber's repository), each with
its attributes, its child elements and whether it holds text.

    python scripts/bcf_schema_names.py            # the releases in TAGS
    python scripts/bcf_schema_names.py v2.23      # these releases, added to the file

tests/test_texinstall.py compares these names with export.BCF_SHAPE. The schema files are
biber's own, read as data from its repository; nothing in them is run."""
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

URL = "https://raw.githubusercontent.com/plk/biber/{tag}/data/schemata/bcf.rng"
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bcf_schema_names.json"
TAGS = ["v2.14", "v2.15", "v2.16", "v2.17", "v2.18", "v2.19", "v2.20", "v2.21", "v2.22"]
RNG = "{http://relaxng.org/ns/structure/1.0}"


def names(text):
    """{element: [attributes, child elements, holds text]} of one RELAX NG schema. An element
    declared in several places has the union of what each declaration allows."""
    root = ET.fromstring(text)
    defines = {define.get("name"): define for define in root.iter(RNG + "define")}
    found = {}

    def content(node, attributes, children, text, seen):
        for child in node:
            kind = child.tag[len(RNG):]
            if kind == "element":
                children.add(child.get("name").split(":")[-1])
            elif kind == "attribute":
                attributes.add(child.get("name"))
            elif kind == "ref":
                if child.get("name") not in seen:
                    content(defines[child.get("name")], attributes, children, text, seen | {child.get("name")})
            elif kind in ("text", "data", "value"):
                text.append(kind)
            else:
                content(child, attributes, children, text, seen)

    for element in root.iter(RNG + "element"):
        name = element.get("name").split(":")[-1]
        attributes, children, text = set(), set(), []
        content(element, attributes, children, text, frozenset())
        earlier = found.get(name, [[], [], False])
        found[name] = [sorted(attributes | set(earlier[0])), sorted(children | set(earlier[1])), bool(text) or earlier[2]]
    return dict(sorted(found.items()))


def main(tags):
    result = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for tag in tags:
        with urllib.request.urlopen(URL.format(tag=tag), timeout=60) as reply:
            result[tag.lstrip("v")] = names(reply.read())
        print(f"biber {tag.lstrip('v')}: {len(result[tag.lstrip('v')])} elements")
    OUT.write_text(json.dumps(dict(sorted(result.items())), indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:] or TAGS)
