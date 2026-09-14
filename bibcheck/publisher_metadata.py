"""Read publisher citation metadata from HTML head, never cited references."""

from collections import defaultdict
from html.parser import HTMLParser


class PublisherMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.values = defaultdict(list)

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        elif tag == "meta" and self.in_head:
            attrs = dict(attrs)
            name = attrs.get("name", "").lower()
            value = attrs.get("content", "").strip()
            if (
                name.startswith("citation_")
                and value
                and value not in self.values[name]
            ):
                self.values[name].append(value)

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False

    def source_metadata(self):
        # Preserve conflicting duplicates rather than quietly choosing a title,
        # DOI or date. This is source evidence, not a verified citation record.
        return {key: values for key, values in self.values.items()}

    @property
    def urls(self):
        return self.values.get("citation_pdf_url", [])
