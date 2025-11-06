# BibTeX Entry Verification Tool (bibverify.py)

## Overview

`bibverify.py` is an automated bibliographic accuracy verification tool that checks entries in BibTeX files against external scholarly databases (primarily CrossRef) to ensure accuracy of metadata including titles, authors, publication years, journals, and more.

## Key Features

- **Automated Verification**: Validates bibliographic entries against CrossRef's database of 170M+ scholarly works
- **Parallel Processing**: Uses multi-threading to verify entries concurrently for significantly faster execution
- **Dual Lookup Strategy**:
  - Primary: DOI-based lookup (most accurate)
  - Fallback: Title and author-based fuzzy matching
- **Smart Matching**: Fuzzy string matching for titles and author names to handle formatting variations
- **Comprehensive Checking**: Verifies titles, authors, years, journals/venues, volumes, pages, and DOIs
- **Detailed Reporting**: Provides clear summaries of verified entries, errors, and suggested corrections
- **Future Auto-fix**: Framework in place for automatic correction of discrepancies (to be implemented)

## Installation

The tool requires Python 3.6+ and several dependencies. Install them using:

```bash
pip install -r requirements.txt
```

Additional dependencies (if not already included):
```bash
pip install requests bibtexparser typer tqdm
```

## Usage

### Basic Verification

Verify all entries in a BibTeX file:

```bash
python bibverify.py verify cdl.bib
```

### Verbose Mode

Get detailed output during verification:

```bash
python bibverify.py verify cdl.bib --verbose
```

### Parallel Processing Options

By default, the tool uses 5 parallel workers. You can adjust this:

```bash
# Use 10 parallel workers for faster processing
python bibverify.py verify cdl.bib --workers 10

# Disable parallel processing (sequential mode)
python bibverify.py verify cdl.bib --no-parallel
```

### Command Line Options

```
python bibverify.py verify [OPTIONS] [BIBFILE]

Arguments:
  BIBFILE                     BibTeX file to verify [default: cdl.bib]

Options:
  --autofix                   Automatically fix discrepancies [NOT YET IMPLEMENTED]
  --outfile TEXT              Output file for corrected bibliography
  -v, --verbose               Verbose output with detailed logging
  --max INTEGER               Maximum entries to verify (for testing)
  --parallel/--no-parallel    Use parallel processing [default: parallel]
  -w, --workers INTEGER       Number of parallel workers [default: 5]
  --help                      Show help message
```

### Get Tool Information

```bash
python bibverify.py info
```

## How It Works

1. **Loading**: Parses the BibTeX file using `bibtexparser`
2. **Parallel Processing**: Distributes entries across multiple worker threads
3. **CrossRef Lookup**:
   - If DOI exists: Direct lookup via DOI (most reliable)
   - If no DOI: Search by title and first author name
4. **Conservative Match Verification** (CRITICAL):
   - **Before reporting any discrepancies**, verifies this is actually the same paper
   - Requires ALL of the following to match:
     - Title similarity ≥ 85%
     - Author similarity ≥ 70%
     - Journal similarity ≥ 60% (if journal present)
     - Year difference ≤ 1 year
   - **Rejects uncertain matches** rather than reporting false positives
   - Example: GuoEtal20 would match a different paper by title alone, but is correctly rejected due to 0% author match
5. **Metadata Verification** (only after confident match):
   - Volume numbers
   - Issue/number
   - Page ranges
   - Detects common errors (e.g., DOI in pages field)
6. **Reporting**: Only reports discrepancies when confident it's the same paper

## Verification Results

The tool categorizes entries as:

- ✓ **Verified**: Entry matches CrossRef data (within tolerance thresholds)
- ✗ **Errors**: Discrepancies found between BibTeX and CrossRef
- ⚠ **Warnings**: Unable to find verification data in CrossRef

### Example Output

```
============================================================
VERIFICATION SUMMARY
============================================================
✓ Verified: 5847
✗ Errors: 289
⚠ Warnings: 15

============================================================
DISCREPANCIES FOUND (289 entries)
============================================================

SmithEtal20:
  Year mismatch: 2020 vs 2019
  DOI missing, can add: 10.1000/example.doi

JohnDoe21:
  Title mismatch (similarity: 78%)
    BibTeX:   An study of machine learning
    CrossRef: A study of machine learning
  ...
```

## Performance

### Comparison: Sequential vs Parallel Processing

For a bibliography with 6,151 entries:

| Mode | Workers | Estimated Time |
|------|---------|----------------|
| Sequential | 1 | ~5-8 hours (50ms delay per entry) |
| Parallel | 5 | ~1-2 hours |
| Parallel | 10 | ~30-60 minutes |
| Parallel | 20 | ~15-30 minutes |

**Note**: Higher worker counts can speed up processing, but be respectful of the CrossRef API. The tool includes rate limiting to avoid overloading their servers.

## API Information

### CrossRef API

- **Base URL**: https://api.crossref.org/
- **Coverage**: 170M+ records
- **Rate Limits**: Free, unlimited (with polite usage)
- **Authentication**: Not required
- **Documentation**: https://github.com/CrossRef/rest-api-doc

The tool uses polite practices:
- Custom User-Agent header
- Rate limiting between requests
- Efficient query parameters

## Discrepancy Types

**Note**: The tool only reports discrepancies when it's confident it found the same paper. This prevents false positives like suggesting corrections based on a completely different paper.

### Volume/Number Mismatches
- Incorrect volume or issue numbers
- Typos in metadata
- Example: `Volume mismatch: '34' vs '35'`

### Page Range Errors
- Incorrect page numbers
- **DOI in pages field** (common error)
- Format inconsistencies
- Example: `Pages field contains DOI, should be: 123-456`

### Year Discrepancies
- ±1 year difference flagged as potential preprint vs published
- Larger differences may indicate wrong entry
- Example: `Year off by 1: 2020 vs 2019 (preprint vs published?)`

### Non-Matches (Warnings)
The tool will NOT report discrepancies in these cases:
- **No data found in CrossRef** (20% of entries)
- **Low title similarity** (< 85%) - might be different paper
- **Low author similarity** (< 70%) - likely different paper
- **Low journal similarity** (< 60%) - uncertain match
- **Year difference > 1 year** - probably different version/paper

This conservative approach prevents false positives like the GuoEtal20 case where a title search might match a completely different paper.

## Integration with Existing Workflow

This tool complements the existing `bibcheck.py` tool:

- **bibcheck.py**: Validates formatting and consistency (keys, author names, capitalization, page numbers, etc.)
- **bibverify.py**: Validates accuracy against external sources (correctness of metadata)

Recommended workflow:
```bash
# Step 1: Verify bibliographic accuracy
python bibverify.py verify cdl.bib --verbose

# Step 2: Check formatting consistency
python bibcheck.py verify --verbose

# Step 3: If both pass, commit
python bibcheck.py commit --verbose
```

## Limitations

1. **Not all entries will be in CrossRef**: Some sources (arXiv preprints, technical reports, older works) may not be indexed
2. **Fuzzy matching isn't perfect**: Very similar titles might match incorrectly in rare cases
3. **Formatting differences**: LaTeX formatting in BibTeX may differ from CrossRef's plain text
4. **Auto-fix not yet implemented**: Currently requires manual correction of discrepancies
5. **Rate limiting**: Even with parallel processing, checking 6000+ entries takes significant time

## Future Enhancements

- [ ] Implement auto-fix functionality with safety checks
- [ ] Add Semantic Scholar API as alternative/complementary source
- [ ] Support for batch processing with resume capability
- [ ] Export discrepancy reports to CSV/JSON
- [ ] Integration with bibcheck.py for unified workflow
- [ ] Caching of API results to speed up re-runs
- [ ] More sophisticated author name matching
- [ ] Support for additional field verification (abstract, keywords, etc.)

## Troubleshooting

### No verification data found

This is normal for:
- Preprints not yet published
- Very recent publications
- Technical reports
- Theses and dissertations
- Some conference papers

### False positive mismatches

Common causes:
- LaTeX formatting in titles (`{COVID-19}` vs `COVID-19`)
- Author name variations (initials vs full names)
- Journal name abbreviations

Consider adding the `force` field to skip verification for these entries:
```bibtex
@article{SpecialCase,
  author = {...},
  title = {...},
  force = {True}
}
```

### API errors

If you encounter API errors:
1. Check internet connection
2. Reduce worker count (try `--workers 3`)
3. CrossRef API may be temporarily down (rare)

## Contributing

Issues, suggestions, and pull requests welcome!

## References

- CrossRef REST API: https://github.com/CrossRef/rest-api-doc
- Related Issue: #37 (Automated bibliographic accuracy verification)

## License

This tool is part of the CDL-bibliography project. See main repository for license information.
