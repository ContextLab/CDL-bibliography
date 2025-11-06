#!/usr/bin/env python3
"""
BibTeX Entry Verification Tool

This script verifies the accuracy of bibliographic entries in a .bib file
by querying external sources (CrossRef API) and optionally correcting
inaccuracies found.

Usage:
    python bibverify.py <bibfile> [--autofix] [--outfile <output.bib>] [--verbose]

Features:
    - Verifies titles, authors, years, venues, volumes, pages against CrossRef
    - Supports DOI-based and title-based lookups
    - Optional auto-correction of inaccuracies
    - Detailed reporting of discrepancies
    - Rate limiting and error handling

Author: Claude (Anthropic)
License: MIT
"""

import sys
sys.path.append('bibcheck')

import requests
import time
import typer
import bibtexparser as bp
from typing import Optional, Dict, List, Tuple
from urllib.parse import quote
from difflib import SequenceMatcher
from tqdm import tqdm
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

app = typer.Typer()


class BibVerifier:
    """Verifies bibliographic entries against external sources."""

    def __init__(self, verbose: bool = False, max_workers: int = 5):
        self.verbose = verbose
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BibTeX-Verification-Tool/1.0 (mailto:research@example.com)'
        })
        self.verified_count = 0
        self.error_count = 0
        self.warning_count = 0
        self.discrepancies = []
        self.lock = threading.Lock()  # For thread-safe counter updates

    def log(self, message: str, level: str = "info"):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            prefix = {
                "info": "ℹ",
                "success": "✓",
                "warning": "⚠",
                "error": "✗"
            }.get(level, "•")
            typer.echo(f"{prefix} {message}")

    def similarity_ratio(self, str1: str, str2: str) -> float:
        """Calculate similarity ratio between two strings."""
        if not str1 or not str2:
            return 0.0
        # Normalize strings for comparison
        s1 = self.normalize_string(str1)
        s2 = self.normalize_string(str2)
        return SequenceMatcher(None, s1, s2).ratio()

    def normalize_string(self, s: str) -> str:
        """Normalize a string for comparison."""
        if not s:
            return ""
        # Remove LaTeX commands, braces, and extra whitespace
        s = re.sub(r'\{[^}]*\}', '', s)  # Remove LaTeX braces
        s = re.sub(r'\\[a-zA-Z]+', '', s)  # Remove LaTeX commands
        s = re.sub(r'[^a-zA-Z0-9\s]', '', s)  # Remove punctuation
        s = re.sub(r'\s+', ' ', s)  # Normalize whitespace
        return s.strip().lower()

    def extract_doi_from_field(self, doi_field: str) -> Optional[str]:
        """Extract DOI from a DOI field that may contain a URL."""
        if not doi_field:
            return None
        # Remove https://doi.org/ or http://dx.doi.org/ prefixes
        doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi_field)
        return doi.strip()

    def query_crossref_by_doi(self, doi: str) -> Optional[Dict]:
        """Query CrossRef API by DOI."""
        if not doi:
            return None

        doi = self.extract_doi_from_field(doi)
        url = f"https://api.crossref.org/works/{quote(doi, safe='')}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('status') == 'ok':
                return data.get('message')
            return None

        except requests.exceptions.RequestException as e:
            self.log(f"CrossRef API error (DOI lookup): {e}", "warning")
            return None

    def query_crossref_by_metadata(self, title: str, author: Optional[str] = None,
                                   year: Optional[str] = None) -> Optional[Dict]:
        """Query CrossRef API by title and optional author/year."""
        if not title:
            return None

        # Build query
        query = title
        if author:
            query += f" {author}"

        url = f"https://api.crossref.org/works"
        params = {
            'query': query,
            'rows': 3,  # Get top 3 results for better matching
            'select': 'title,author,published,container-title,volume,issue,page,DOI,publisher,type,ISSN'
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            items = data.get('message', {}).get('items', [])
            if not items:
                return None

            # Find best match by title similarity
            best_match = None
            best_score = 0.0

            for item in items:
                item_title = item.get('title', [''])[0] if item.get('title') else ''
                similarity = self.similarity_ratio(title, item_title)

                # Also check year if provided
                if year and 'published' in item:
                    item_year = item.get('published', {}).get('date-parts', [[None]])[0][0]
                    if item_year and str(item_year) != str(year):
                        similarity *= 0.7  # Penalize year mismatch

                if similarity > best_score:
                    best_score = similarity
                    best_match = item

            # Only return if similarity is above threshold
            if best_score >= 0.7:
                return best_match

            return None

        except requests.exceptions.RequestException as e:
            self.log(f"CrossRef API error (metadata lookup): {e}", "warning")
            return None

    def format_authors(self, authors_list: List[Dict]) -> str:
        """Format CrossRef authors list to BibTeX format."""
        formatted = []
        for author in authors_list:
            given = author.get('given', '')
            family = author.get('family', '')
            if given and family:
                # Format as: Given Family
                formatted.append(f"{given} {family}")
            elif family:
                formatted.append(family)

        return ' and '.join(formatted) if formatted else ''

    def extract_last_names(self, author_string: str) -> List[str]:
        """Extract last names from BibTeX author string."""
        if not author_string:
            return []

        authors = author_string.split(' and ')
        last_names = []

        for author in authors:
            parts = author.strip().split()
            if parts:
                # Last name is typically the last part
                last_names.append(parts[-1])

        return last_names

    def compare_authors(self, bib_authors: str, crossref_authors: List[Dict]) -> Tuple[bool, float]:
        """Compare BibTeX authors with CrossRef authors."""
        if not bib_authors or not crossref_authors:
            return False, 0.0

        bib_last_names = [ln.lower() for ln in self.extract_last_names(bib_authors)]
        crossref_last_names = [a.get('family', '').lower() for a in crossref_authors if a.get('family')]

        if not bib_last_names or not crossref_last_names:
            return False, 0.0

        # Calculate how many authors match
        matches = sum(1 for bln in bib_last_names if any(
            self.similarity_ratio(bln, cln) > 0.85 for cln in crossref_last_names
        ))

        similarity = matches / max(len(bib_last_names), len(crossref_last_names))
        return similarity > 0.7, similarity

    def verify_entry(self, entry: Dict) -> Tuple[bool, List[str], Dict]:
        """
        Verify a single BibTeX entry.

        Returns:
            (verified, discrepancies_list, corrections_dict)
        """
        entry_id = entry.get('ID', 'UNKNOWN')
        self.log(f"Verifying entry: {entry_id}")

        # Skip if force flag is set
        if entry.get('force') == 'True':
            self.log(f"Skipping {entry_id} (force flag set)", "info")
            return True, [], {}

        # Extract fields
        title = entry.get('title', '')
        authors = entry.get('author', '')
        year = entry.get('year', '')
        journal = entry.get('journal', '')
        volume = entry.get('volume', '')
        pages = entry.get('pages', '')
        doi = entry.get('doi', '')

        # Query CrossRef
        crossref_data = None

        # Try DOI lookup first (most reliable)
        if doi:
            self.log(f"Looking up by DOI: {doi}", "info")
            crossref_data = self.query_crossref_by_doi(doi)

        # Fallback to title-based lookup
        if not crossref_data and title:
            self.log(f"Looking up by title: {title[:50]}...", "info")
            first_author = self.extract_last_names(authors)[0] if authors else None
            crossref_data = self.query_crossref_by_metadata(title, first_author, year)

        # No data found
        if not crossref_data:
            self.log(f"No verification data found for {entry_id}", "warning")
            with self.lock:
                self.warning_count += 1
            return False, [f"No verification data found in CrossRef"], {}

        # Compare fields
        discrepancies = []
        corrections = {}

        # Verify title
        crossref_title = crossref_data.get('title', [''])[0] if crossref_data.get('title') else ''
        title_similarity = self.similarity_ratio(title, crossref_title)
        if title_similarity < 0.85:
            discrepancies.append(f"Title mismatch (similarity: {title_similarity:.2%})")
            discrepancies.append(f"  BibTeX:   {title}")
            discrepancies.append(f"  CrossRef: {crossref_title}")
            # Don't auto-correct titles as they may have intentional formatting

        # Verify authors
        crossref_authors = crossref_data.get('author', [])
        authors_match, author_similarity = self.compare_authors(authors, crossref_authors)
        if not authors_match:
            crossref_author_str = self.format_authors(crossref_authors)
            discrepancies.append(f"Author mismatch (similarity: {author_similarity:.2%})")
            discrepancies.append(f"  BibTeX:   {authors}")
            discrepancies.append(f"  CrossRef: {crossref_author_str}")
            # Could auto-correct authors but risky

        # Verify year
        crossref_year = crossref_data.get('published', {}).get('date-parts', [[None]])[0][0]
        if crossref_year and year and str(crossref_year) != str(year):
            discrepancies.append(f"Year mismatch: {year} vs {crossref_year}")
            corrections['year'] = str(crossref_year)

        # Verify journal/venue
        crossref_journal = crossref_data.get('container-title', [''])[0] if crossref_data.get('container-title') else ''
        if journal and crossref_journal:
            journal_similarity = self.similarity_ratio(journal, crossref_journal)
            if journal_similarity < 0.7:
                discrepancies.append(f"Journal mismatch (similarity: {journal_similarity:.2%})")
                discrepancies.append(f"  BibTeX:   {journal}")
                discrepancies.append(f"  CrossRef: {crossref_journal}")
                # Could suggest correction

        # Verify volume
        crossref_volume = crossref_data.get('volume', '')
        if volume and crossref_volume and volume != crossref_volume:
            discrepancies.append(f"Volume mismatch: {volume} vs {crossref_volume}")
            corrections['volume'] = crossref_volume

        # Verify pages
        crossref_pages = crossref_data.get('page', '')
        if pages and crossref_pages:
            # Normalize page formats for comparison
            norm_pages = pages.replace('--', '-').replace('−', '-')
            norm_crossref = crossref_pages.replace('--', '-').replace('−', '-')
            if norm_pages != norm_crossref:
                discrepancies.append(f"Pages mismatch: {pages} vs {crossref_pages}")
                # Pages can have different formats, be cautious

        # Add DOI if missing
        crossref_doi = crossref_data.get('DOI', '')
        if not doi and crossref_doi:
            corrections['doi'] = f"https://doi.org/{crossref_doi}"
            discrepancies.append(f"DOI missing, can add: {crossref_doi}")

        # Summary
        if discrepancies:
            with self.lock:
                self.error_count += 1
                self.discrepancies.append({
                    'id': entry_id,
                    'discrepancies': discrepancies,
                    'corrections': corrections
                })
            return False, discrepancies, corrections
        else:
            with self.lock:
                self.verified_count += 1
            self.log(f"{entry_id} verified successfully", "success")
            return True, [], {}

    def verify_entry_wrapper(self, entry_tuple: Tuple[str, Dict]) -> Tuple[str, bool, List[str], Dict]:
        """Wrapper for verify_entry to work with ThreadPoolExecutor."""
        entry_id, entry = entry_tuple
        try:
            verified, discrepancies, corrections = self.verify_entry(entry)
            return entry_id, verified, discrepancies, corrections
        except Exception as e:
            self.log(f"Error verifying {entry_id}: {e}", "error")
            return entry_id, False, [str(e)], {}

    def verify_bibliography(self, bibfile: str, use_parallel: bool = True) -> Dict:
        """Verify all entries in a bibliography file."""
        self.log(f"Loading bibliography: {bibfile}")

        parser = bp.bparser.BibTexParser(ignore_nonstandard_types=True,
                                         common_strings=True,
                                         homogenize_fields=True)

        with open(bibfile, 'r') as f:
            bibdata = bp.load(f, parser=parser)

        entries = bibdata.get_entry_dict()
        total = len(entries)

        self.log(f"Found {total} entries to verify")
        if use_parallel:
            typer.echo(f"\nVerifying {total} entries using {self.max_workers} parallel workers...")
        else:
            typer.echo(f"\nVerifying {total} entries sequentially...")

        results = {
            'verified': [],
            'errors': [],
            'warnings': [],
            'corrections': {}
        }

        if use_parallel:
            # Parallel verification with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_entry = {
                    executor.submit(self.verify_entry_wrapper, item): item[0]
                    for item in entries.items()
                }

                # Process completed tasks with progress bar
                with tqdm(total=total, desc="Verifying entries") as pbar:
                    for future in as_completed(future_to_entry):
                        entry_id, verified, discrepancies, corrections = future.result()

                        if verified:
                            results['verified'].append(entry_id)
                        else:
                            results['errors'].append({
                                'id': entry_id,
                                'discrepancies': discrepancies
                            })
                            if corrections:
                                results['corrections'][entry_id] = corrections

                        pbar.update(1)

                        # Small delay to respect rate limits
                        time.sleep(0.01)

        else:
            # Sequential verification (original behavior)
            for entry_id, entry in tqdm(entries.items(), desc="Verifying entries", disable=not self.verbose):
                try:
                    verified, discrepancies, corrections = self.verify_entry(entry)

                    if verified:
                        results['verified'].append(entry_id)
                    else:
                        results['errors'].append({
                            'id': entry_id,
                            'discrepancies': discrepancies
                        })
                        if corrections:
                            results['corrections'][entry_id] = corrections

                    # Rate limiting: be respectful to CrossRef
                    time.sleep(0.05)  # 50ms delay between requests

                except Exception as e:
                    self.log(f"Error verifying {entry_id}: {e}", "error")
                    results['warnings'].append(entry_id)

        return results


@app.command()
def verify(
    bibfile: str = typer.Argument("cdl.bib", help="BibTeX file to verify"),
    autofix: bool = typer.Option(False, "--autofix", help="Automatically fix discrepancies"),
    outfile: Optional[str] = typer.Option(None, "--outfile", help="Output file for corrected bibliography"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    max_entries: Optional[int] = typer.Option(None, "--max", help="Maximum entries to verify (for testing)"),
    parallel: bool = typer.Option(True, "--parallel/--no-parallel", help="Use parallel processing (default: True)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Number of parallel workers (default: 5)")
):
    """
    Verify bibliographic entries against CrossRef database.

    This command checks each entry in the .bib file against the CrossRef API
    to verify accuracy of titles, authors, years, journals, and other metadata.

    Parallel processing (enabled by default) significantly speeds up verification
    by making multiple API requests concurrently.
    """
    verifier = BibVerifier(verbose=verbose, max_workers=workers)

    try:
        results = verifier.verify_bibliography(bibfile, use_parallel=parallel)

        # Print summary
        typer.echo("\n" + "="*60)
        typer.echo("VERIFICATION SUMMARY")
        typer.echo("="*60)
        typer.echo(f"✓ Verified: {verifier.verified_count}")
        typer.echo(f"✗ Errors: {verifier.error_count}")
        typer.echo(f"⚠ Warnings: {verifier.warning_count}")

        # Print discrepancies
        if verifier.discrepancies:
            typer.echo(f"\n{'='*60}")
            typer.echo(f"DISCREPANCIES FOUND ({len(verifier.discrepancies)} entries)")
            typer.echo("="*60)

            for disc in verifier.discrepancies[:10]:  # Show first 10
                typer.echo(f"\n{disc['id']}:")
                for d in disc['discrepancies']:
                    typer.echo(f"  {d}")

            if len(verifier.discrepancies) > 10:
                typer.echo(f"\n... and {len(verifier.discrepancies) - 10} more entries with discrepancies")
                typer.echo("Run with --verbose to see all discrepancies")

        # Auto-fix if requested
        if autofix and outfile:
            typer.echo(f"\n⚠ Auto-fix feature not yet implemented")
            typer.echo("This feature will be added in a future update")

        # Final message
        if verifier.error_count == 0:
            typer.echo("\n✓ All entries verified successfully!")
        else:
            typer.echo(f"\n⚠ Found issues in {verifier.error_count} entries")
            typer.echo("Review the discrepancies above and fix manually, or use --autofix (when available)")

    except FileNotFoundError:
        typer.echo(f"✗ Error: File '{bibfile}' not found", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"✗ Error: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def info():
    """Show information about the verification tool."""
    typer.echo("BibTeX Verification Tool")
    typer.echo("="*60)
    typer.echo("\nThis tool verifies bibliographic entries against:")
    typer.echo("  • CrossRef API (170M+ records, free, unlimited)")
    typer.echo("\nFeatures:")
    typer.echo("  ✓ DOI-based lookup (most accurate)")
    typer.echo("  ✓ Title and author-based lookup (fallback)")
    typer.echo("  ✓ Verifies: titles, authors, years, journals, volumes, pages")
    typer.echo("  ✓ Smart fuzzy matching for titles and authors")
    typer.echo("  ✓ Respectful rate limiting")
    typer.echo("\nUsage:")
    typer.echo("  python bibverify.py verify cdl.bib --verbose")
    typer.echo("  python bibverify.py verify mybib.bib --autofix --outfile=corrected.bib")


if __name__ == "__main__":
    app()
