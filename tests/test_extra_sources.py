"""Extra metadata routes (bibcheck/extra_sources.py) on real cached records.

Fixtures are short excerpts of responses retrieved on 2026-09-23 into
.bibcheck/extra-sources.sqlite3 (abstracts, MeSH terms and affiliations cut;
nothing else edited). Citations are the cdl.bib entries named in each test,
or a stated one-field change of them (negative and positive controls).
See verification/extra-sources-2026-09-23/README.md.
"""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import extra_sources as xs  # noqa: E402
from verification import Cache, ProviderError, dumps  # noqa: E402

# PMID 13896567 (efetch, 2026-09-23): Games 1962, J Exp Psychol 63:1-11.
GAMES_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM" IndexingMethod="Automated"><PMID Version="1">13896567</PMID><Article PubModel="Print"><Journal><ISSN IssnType="Print">0022-1015</ISSN><JournalIssue CitedMedium="Print"><Volume>63</Volume><PubDate><Year>1962</Year><Month>Jan</Month></PubDate></JournalIssue><Title>Journal of experimental psychology</Title><ISOAbbreviation>J Exp Psychol</ISOAbbreviation></Journal><ArticleTitle>A factorial analysis of verbal learning tasks.</ArticleTitle><Pagination><StartPage>1</StartPage><EndPage>11</EndPage><MedlinePgn>1-11</MedlinePgn></Pagination><AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>GAMES</LastName><ForeName>P A</ForeName><Initials>PA</Initials></Author></AuthorList><Language>eng</Language><PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList></Article><MedlineJournalInfo><Country>United States</Country><MedlineTA>J Exp Psychol</MedlineTA><NlmUniqueID>7502586</NlmUniqueID><ISSNLinking>0022-1015</ISSNLinking></MedlineJournalInfo><CitationSubset>OM</CitationSubset></MedlineCitation><PubmedData><PublicationStatus>ppublish</PublicationStatus><ArticleIdList><ArticleId IdType="pubmed">13896567</ArticleId><ArticleId IdType="doi">10.1037/h0041332</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

# PMID 12049324 (efetch, 2026-09-23): no DOI in PubMed; the byline order is Asaka, Griffin, Berry.
BERRY_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM" IndexingMethod="Manual"><PMID Version="1">12049324</PMID><Article PubModel="Print"><Journal><ISSN IssnType="Print">0735-7044</ISSN><JournalIssue CitedMedium="Print"><Volume>116</Volume><Issue>3</Issue><PubDate><Year>2002</Year><Month>Jun</Month></PubDate></JournalIssue><Title>Behavioral neuroscience</Title><ISOAbbreviation>Behav Neurosci</ISOAbbreviation></Journal><ArticleTitle>Reversible septal inactivation disrupts hippocampal slow-wave and unit activity and impairs trace conditioning in rabbits (Oryctolagus cuniculus).</ArticleTitle><Pagination><StartPage>434</StartPage><EndPage>442</EndPage><MedlinePgn>434-42</MedlinePgn></Pagination><AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>Asaka</LastName><ForeName>Yukiko</ForeName><Initials>Y</Initials></Author><Author ValidYN="Y"><LastName>Griffin</LastName><ForeName>Amy L</ForeName><Initials>AL</Initials></Author><Author ValidYN="Y"><LastName>Berry</LastName><ForeName>Stephen D</ForeName><Initials>SD</Initials></Author></AuthorList><Language>eng</Language><PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType><PublicationType UI="D013487">Research Support, U.S. Gov't, P.H.S.</PublicationType></PublicationTypeList></Article><MedlineJournalInfo><Country>United States</Country><MedlineTA>Behav Neurosci</MedlineTA><NlmUniqueID>8302411</NlmUniqueID><ISSNLinking>0735-7044</ISSNLinking></MedlineJournalInfo><CitationSubset>IM</CitationSubset></MedlineCitation><PubmedData><PublicationStatus>ppublish</PublicationStatus><ArticleIdList><ArticleId IdType="pubmed">12049324</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

GAMES62 = {"ENTRYTYPE": "article", "ID": "Game62", "author": "P A Games",
           "journal": "Journal of Experimental Psychology: General", "number": "1", "pages": "1--11",
           "title": "A factorial analysis of verbal learning tasks", "volume": "63", "year": "1962"}
BERRETAL02 = {"ENTRYTYPE": "article", "ID": "BerrEtal02", "author": "S D Berry and Y Asaka and A L Griffin",
              "journal": "Behavioral Neuroscience", "pages": "434--442",
              "title": "Reversible septal inactivitation disrupts hippocampal slow-wave and unit activity and "
                       "impairs trace conditioning in rabbits {(Oryctolagus} cuniculus)",
              "volume": "116", "year": "2002"}
# The same article cited with PubMed's byline order and title (derived control).
BERRY_AS_INDEXED = dict(BERRETAL02, author="Yukiko Asaka and Amy L Griffin and Stephen D Berry",
                        title="Reversible septal inactivation disrupts hippocampal slow-wave and unit activity "
                              "and impairs trace conditioning in rabbits ({Oryctolagus} cuniculus)",
                        number="3")

# Crossref 10.1038/319774a0 and 10.31234/osf.io/bmt4s (retrieved 2026-09-23; selected fields).
MORRIS_1986 = {"DOI": "10.1038/319774a0", "type": "journal-article",
               "title": ["Selective impairment of learning and blockade of long-term potentiation by an "
                         "N-methyl-D-aspartate receptor antagonist, AP5"],
               "author": [{"family": "Morris", "given": "R. G. M.", "sequence": "first"},
                          {"family": "Anderson", "given": "E.", "sequence": "additional"},
                          {"family": "Lynch", "given": "G. S.", "sequence": "additional"},
                          {"family": "Baudry", "given": "M.", "sequence": "additional"}],
               "container-title": ["Nature"], "volume": "319", "issue": "6056", "page": "774-776",
               "published": {"date-parts": [[1986, 2]]}, "issued": {"date-parts": [[1986, 2]]},
               "published-print": {"date-parts": [[1986, 2]]}, "relation": {}, "ISSN": ["0028-0836", "1476-4687"],
               "subtitle": []}
MORRETAL86 = {"ENTRYTYPE": "article", "ID": "MorrEtal86", "author": "R Morris and E Anderson and G Lynch and M Baudry",
              "journal": "Nature", "pages": "774--776", "volume": "319", "year": "1986",
              "title": "Selective impairment of leraning and blockade of long-term potentiation by an {NMDA} "
                       "receptor antagonist"}
COHN_PREPRINT = {"DOI": "10.31234/osf.io/bmt4s", "type": "posted-content",
                 "title": ["Narratives bridge the divide between distant events in episodic memory"],
                 "author": [{"family": n.split()[-1], "given": " ".join(n.split()[:-1])} for n in (
                     "Brendan I Cohn-Sheehy", "Angelique Delarazan", "Jordan E. Crivelli-Decker",
                     "Zachariah Reagh", "Nidhi Mundada", "Andrew Yonelinas", "Jeffrey M. Zacks",
                     "Charan Ranganath")],
                 "container-title": [], "published": {"date-parts": [[2020, 9, 23]]},
                 "issued": {"date-parts": [[2020, 9, 23]]}, "relation": {}, "subtitle": []}
COHNETAL21 = {"ENTRYTYPE": "article", "ID": "CohnEtal21",
              "author": "B I Cohn-Sheehy and A I Delarazan and J E Crivelli-Decker and Z M Reagh and N S Mundada "
                        "and A P Yonelinas and J M Zacks and C Ranganath",
              "journal": "Memory and Cognition", "pages": "1--17", "year": "2021",
              "title": "Narratives bridge the divide between distant events in episodic memory"}


def entry(fields):
    return {"key": fields["ID"], "fingerprint": "test", "fields": dict(fields)}


def medline(xml):
    return xs.parse_medline(xml)


# --------------------------------------------------------------------------
# MEDLINE parsing


def test_parse_medline_fields():
    raw = medline(GAMES_XML)["13896567"]
    assert raw["title"] == "A factorial analysis of verbal learning tasks."
    assert raw["volume"] == "63" and raw["issue"] == "" and raw["year"] == "1962"
    assert raw["pages"] == "1-11" and raw["dois"] == ["10.1037/h0041332"]
    assert raw["authors"] == [{"family": "GAMES", "fore": "P A", "initials": "PA", "suffix": ""}]
    record = xs.medline_record(raw)
    assert record["title"] == ["A factorial analysis of verbal learning tasks"]  # one final period dropped
    assert record["page"] == "1-11" and record["DOI"] == "10.1037/h0041332"


def test_abbreviated_pages_are_expanded():
    record = xs.medline_record(medline(BERRY_XML)["12049324"])
    assert record["page"] == "434-442" and "DOI" not in record


def test_not_a_pubmed_set_is_an_error():
    with pytest.raises(ProviderError):
        xs.parse_medline("<eSearchResult><ERROR>bad</ERROR></eSearchResult>")


def test_nlm_venue_equal_up_to_case_only():
    raw = medline(BERRY_XML)["12049324"]
    assert xs.venue_matches_medline("Behavioral Neuroscience", raw) == "Behavioral neuroscience"
    assert xs.venue_matches_medline("Behavioural Neuroscience", raw) is None
    assert xs.venue_matches_medline("Behavioral Brain Research", raw) is None
    games = medline(GAMES_XML)["13896567"]
    # The 1962 journal is not its 1975 successor "... : General".
    assert xs.venue_matches_medline("Journal of Experimental Psychology: General", games) is None


# --------------------------------------------------------------------------
# PubMed-only judgement: positives


def test_pubmed_only_verifies_a_fully_matching_citation():
    result = xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), medline(BERRY_XML))
    assert result["outcome"] == "verify" and result["pmid"] == "12049324" and result["identity"] == "I1"


def test_pubmed_only_proposes_one_field():
    wrong = dict(BERRY_AS_INDEXED, pages="434--443")
    result = xs.pubmed_only_assessment(entry(wrong), medline(BERRY_XML))
    assert result["outcome"] == "proposal"
    assert result["changes"] == {"pages": {"before": "434--443", "after": "434--442"}}


def test_pubmed_only_title_typo_is_corrected():
    typo = dict(BERRY_AS_INDEXED, title=BERRY_AS_INDEXED["title"].replace("inactivation", "inactivitation"))
    result = xs.pubmed_only_assessment(entry(typo), medline(BERRY_XML))
    assert result["outcome"] == "proposal" and list(result["changes"]) == ["title"]
    assert "inactivation" in result["changes"]["title"]["after"]


# --------------------------------------------------------------------------
# PubMed-only judgement: negative controls


def test_real_citation_with_different_author_order_is_not_identified():
    assert xs.pubmed_only_assessment(entry(BERRETAL02), medline(BERRY_XML))["outcome"] == "none"


def test_different_year_is_not_identified():
    other_year = dict(BERRY_AS_INDEXED, year="2003")
    assert xs.pubmed_only_assessment(entry(other_year), medline(BERRY_XML))["outcome"] == "none"


def test_same_title_different_first_author_is_not_identified():
    other = dict(BERRY_AS_INDEXED, author="J Smith and Amy L Griffin and Stephen D Berry")
    assert xs.pubmed_only_assessment(entry(other), medline(BERRY_XML))["outcome"] == "none"


def test_erratum_record_is_never_the_cited_work():
    notice = BERRY_XML.replace('<PublicationType UI="D016428">Journal Article</PublicationType>',
                               '<PublicationType UI="D016425">Published Erratum</PublicationType>')
    assert xs.medline_is_notice(medline(notice)["12049324"])
    assert xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), medline(notice))["outcome"] == "none"


def test_preprint_record_is_never_the_cited_work():
    preprint = BERRY_XML.replace('<PublicationType UI="D016428">Journal Article</PublicationType>',
                                 '<PublicationType UI="D000076942">Preprint</PublicationType>')
    assert xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), medline(preprint))["outcome"] == "none"


def test_erratum_link_holds():
    linked = BERRY_XML.replace("</MedlineJournalInfo>", "</MedlineJournalInfo><CommentsCorrectionsList>"
                               "<CommentsCorrections RefType=\"ErratumIn\"><RefSource>Behav Neurosci. 2002;116(4)"
                               "</RefSource></CommentsCorrections></CommentsCorrectionsList>")
    result = xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), medline(linked))
    assert result["outcome"] == "held" and result["reason"] == "pubmed-relation"


def test_two_identified_records_are_ambiguous():
    raws = medline(BERRY_XML)
    twin = deepcopy(raws["12049324"])
    twin["pmid"] = "99999999"
    raws["99999999"] = twin
    assert xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), raws)["outcome"] == "ambiguous"


def test_nlm_journal_title_is_never_proposed():
    # Real Game62: I2 identity, but the only fix would copy NLM's venue style.
    result = xs.pubmed_only_assessment(entry(GAMES62), medline(GAMES_XML))
    assert result["identity"] == "I2" and result["outcome"] == "held"


def test_crossref_record_for_the_same_work_takes_precedence():
    crossref = {"DOI": "10.1037/0735-7044.116.3.434", "type": "journal-article",
                "title": ["Reversible septal inactivation disrupts hippocampal slow-wave and unit activity and "
                          "impairs trace conditioning in rabbits (Oryctolagus cuniculus)"],
                "author": [{"family": "Asaka", "given": "Yukiko"}, {"family": "Griffin", "given": "Amy L."},
                           {"family": "Berry", "given": "Stephen D."}],
                "container-title": ["Behavioral Neuroscience"], "volume": "116", "page": "434-442",
                "published": {"date-parts": [[2002]]}}
    result = xs.pubmed_only_assessment(entry(BERRY_AS_INDEXED), medline(BERRY_XML), [crossref])
    assert result["outcome"] == "held" and result["reason"] == "crossref-record-identified"


# --------------------------------------------------------------------------
# Resolver path with new Crossref candidates


def previous_with(*records):
    return {"status": "needs_review", "issues": ["No unambiguous, fully supported metadata match"],
            "candidates": [{"source": "crossref", "doi": r["DOI"], "record": r, "retrieved_at": "2026-09-23"}
                           for r in records], "attempts": []}


def test_title_more_than_two_edits_away_is_not_corrected():
    verdict = xs.judge(entry(MORRETAL86), previous_with(), [previous_with(MORRIS_1986)["candidates"][0]], {})
    assert verdict["outcome"] == "held"
    assert verdict["s1_explain"]["reason"] == "no-identified-record"


def test_preprint_record_does_not_verify_the_article():
    candidate = previous_with(COHN_PREPRINT)["candidates"][0]
    verdict = xs.judge(entry(COHNETAL21), previous_with(), [candidate], {})
    assert verdict["outcome"] == "held"


def test_matching_crossref_lead_verifies():
    # Positive control: the Morris 1986 record, cited exactly as deposited.
    exact = dict(MORRETAL86, title="Selective impairment of learning and blockade of long-term potentiation by "
                                   "an {N}-methyl-{D}-aspartate receptor antagonist, {AP5}",
                 author="R G M Morris and E Anderson and G S Lynch and M Baudry", number="6056")
    verdict = xs.judge(entry(exact), previous_with(), [previous_with(MORRIS_1986)["candidates"][0]], {})
    assert verdict["outcome"] == "verify" and verdict["doi"] == "10.1038/319774a0"


# PMID 30500813 (article, ErratumIn 31059496) and PMID 31059496 (the Published Erratum), efetch 2026-09-24.
PUPIL_ARTICLE_XML = '<PubmedArticleSet>\n<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM" IndexingMethod="Manual"><PMID Version="1">30500813</PMID><Article PubModel="Electronic-eCollection"><Journal><ISSN IssnType="Electronic">1553-7358</ISSN><JournalIssue CitedMedium="Internet"><Volume>14</Volume><Issue>11</Issue><PubDate><Year>2018</Year><Month>Nov</Month></PubDate></JournalIssue><Title>PLoS computational biology</Title><ISOAbbreviation>PLoS Comput Biol</ISOAbbreviation></Journal><ArticleTitle>How pupil responses track value-based decision-making during and after reinforcement learning.</ArticleTitle><Pagination><StartPage>e1006632</StartPage><MedlinePgn>e1006632</MedlinePgn></Pagination><ELocationID EIdType="pii" ValidYN="Y">e1006632</ELocationID><ELocationID EIdType="doi" ValidYN="Y">10.1371/journal.pcbi.1006632</ELocationID><AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>Van Slooten</LastName><ForeName>Joanne C</ForeName><Initials>JC</Initials></Author><Author ValidYN="Y"><LastName>Jahfari</LastName><ForeName>Sara</ForeName><Initials>S</Initials></Author><Author ValidYN="Y"><LastName>Knapen</LastName><ForeName>Tomas</ForeName><Initials>T</Initials></Author><Author ValidYN="Y"><LastName>Theeuwes</LastName><ForeName>Jan</ForeName><Initials>J</Initials></Author></AuthorList><Language>eng</Language><PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType><PublicationType UI="D013485">Research Support, Non-U.S. Gov\'t</PublicationType></PublicationTypeList></Article><MedlineJournalInfo><Country>United States</Country><MedlineTA>PLoS Comput Biol</MedlineTA><NlmUniqueID>101238922</NlmUniqueID><ISSNLinking>1553-734X</ISSNLinking></MedlineJournalInfo><CitationSubset>IM</CitationSubset><CommentsCorrectionsList><CommentsCorrections RefType="ErratumIn"><RefSource>PLoS Comput Biol. 2019 May 6;15(5):e1007031. doi: 10.1371/journal.pcbi.1007031.</RefSource><PMID Version="1">31059496</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation><PubmedData><PublicationStatus>epublish</PublicationStatus><ArticleIdList><ArticleId IdType="pubmed">30500813</ArticleId><ArticleId IdType="pmc">PMC6291167</ArticleId><ArticleId IdType="doi">10.1371/journal.pcbi.1006632</ArticleId><ArticleId IdType="pii">PCOMPBIOL-D-18-01174</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
PUPIL_ERRATUM_XML = '<PubmedArticleSet>\n<PubmedArticle><MedlineCitation Status="PubMed-not-MEDLINE" Owner="NLM"><PMID Version="1">31059496</PMID><Article PubModel="Electronic-eCollection"><Journal><ISSN IssnType="Electronic">1553-7358</ISSN><JournalIssue CitedMedium="Internet"><Volume>15</Volume><Issue>5</Issue><PubDate><Year>2019</Year><Month>May</Month></PubDate></JournalIssue><Title>PLoS computational biology</Title><ISOAbbreviation>PLoS Comput Biol</ISOAbbreviation></Journal><ArticleTitle>Correction: How pupil responses track value-based decision-making during and after reinforcement learning.</ArticleTitle><Pagination><StartPage>e1007031</StartPage><MedlinePgn>e1007031</MedlinePgn></Pagination><ELocationID EIdType="pii" ValidYN="Y">e1007031</ELocationID><ELocationID EIdType="doi" ValidYN="Y">10.1371/journal.pcbi.1007031</ELocationID><AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>Van Slooten</LastName><ForeName>Joanne C</ForeName><Initials>JC</Initials></Author><Author ValidYN="Y"><LastName>Jahfari</LastName><ForeName>Sara</ForeName><Initials>S</Initials></Author><Author ValidYN="Y"><LastName>Knapen</LastName><ForeName>Tomas</ForeName><Initials>T</Initials></Author><Author ValidYN="Y"><LastName>Theeuwes</LastName><ForeName>Jan</ForeName><Initials>J</Initials></Author></AuthorList><Language>eng</Language><PublicationTypeList><PublicationType UI="D016425">Published Erratum</PublicationType></PublicationTypeList></Article><MedlineJournalInfo><Country>United States</Country><MedlineTA>PLoS Comput Biol</MedlineTA><NlmUniqueID>101238922</NlmUniqueID><ISSNLinking>1553-734X</ISSNLinking></MedlineJournalInfo><CommentsCorrectionsList><CommentsCorrections RefType="ErratumFor"><RefSource>PLoS Comput Biol. 2018 Nov 30;14(11):e1006632. doi: 10.1371/journal.pcbi.1006632.</RefSource><PMID Version="1">30500813</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation><PubmedData><PublicationStatus>epublish</PublicationStatus><ArticleIdList><ArticleId IdType="pubmed">31059496</ArticleId><ArticleId IdType="pmc">PMC6502326</ArticleId><ArticleId IdType="doi">10.1371/journal.pcbi.1007031</ArticleId><ArticleId IdType="pii">PCOMPBIOL-D-19-00610</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
VANSETAL18 = {"ENTRYTYPE": "article", "ID": "VanSEtal18", "author": "J C Van Slooten and S Jahfari and T Knapen and J Theeuwes",
              "journal": "{PLoS} Computational Biology", "number": "11", "pages": "e1006632", "volume": "14", "year": "2018",
              "title": "How pupil responses track value-based decision making during and after reinforcement learning"}

# Crossref query.bibliographic, 2026-09-24: a 1933 book review deposited with the book's title and
# the book's author first (Bartlett, then the reviewer Burt).
REMEMBERING_REVIEW = {"DOI": "10.1111/j.2044-8279.1933.tb02913.x", "type": "journal-article",
                      "title": ["REMEMBERING: A STUDY IN EXPERIMENTAL AND SOCIAL PSYCHOLOGY"],
                      "author": [{"family": "Bartlett", "given": "F. C.", "sequence": "first"},
                                 {"family": "Burt", "given": "Cyril", "sequence": "additional"}],
                      "container-title": ["British Journal of Educational Psychology"], "volume": "3",
                      "issue": "2", "page": "187-192", "published": {"date-parts": [[1933, 6]]},
                      "issued": {"date-parts": [[1933, 6]]}, "published-print": {"date-parts": [[1933, 6]]},
                      "relation": None, "subtitle": None}
BART32 = {"ENTRYTYPE": "book", "ID": "Bart32", "author": "F C Bartlett", "publisher": "{Oxford} {University} Press",
          "title": "Remembering: a study in experimental and social psychology", "year": "1932"}


def test_real_erratum_notice_is_excluded_and_the_link_holds():
    raws = dict(medline(PUPIL_ARTICLE_XML), **medline(PUPIL_ERRATUM_XML))
    assert xs.medline_is_notice(raws["31059496"]) and not xs.medline_is_notice(raws["30500813"])
    # cdl.bib writes "J C Van Slooten", which BibTeX splits as given "J C Van": no identity at all.
    assert xs.pubmed_only_assessment(entry(VANSETAL18), raws)["outcome"] == "none"
    braced = dict(VANSETAL18, author=VANSETAL18["author"].replace("J C Van Slooten", "J C {Van Slooten}"))
    result = xs.pubmed_only_assessment(entry(braced), raws)
    assert result["pmid"] == "30500813"  # the notice is never a candidate, so this is not ambiguous
    assert result["outcome"] == "held" and result["reason"] == "pubmed-relation" and "ErratumIn" in result["detail"]


def test_book_review_does_not_verify_the_book():
    candidate = previous_with(REMEMBERING_REVIEW)["candidates"][0]
    assert xs.judge(entry(BART32), previous_with(), [candidate], {})["outcome"] == "held"


def test_book_review_is_not_identified_as_an_article_of_the_book_year():
    from correction_proposals import single_source_identity
    as_article = dict(BART32, ENTRYTYPE="article", journal="British Journal of Educational Psychology",
                      volume="3", pages="187--192")
    assert single_source_identity(as_article, REMEMBERING_REVIEW) is None  # 1932 book, 1933 review


# --------------------------------------------------------------------------
# Lead screening and queries


def test_lead_screening():
    assert xs.lead_matches(COHNETAL21, COHN_PREPRINT["title"][0], ["Cohn-Sheehy"])
    assert not xs.lead_matches(COHNETAL21, COHN_PREPRINT["title"][0], ["Ranganath"])
    assert not xs.lead_matches(COHNETAL21, "Narratives in episodic memory", ["Cohn-Sheehy"])


def test_query_terms():
    assert xs.pubmed_citation_term(BERRETAL02) == "116[vi] AND 434[pg] AND 2002[dp] AND berry[au]"
    assert xs.pubmed_citation_term(COHNETAL21) is None  # no volume
    term = xs.pubmed_title_term(GAMES62)
    assert term == "factorial[ti] AND analysis[ti] AND verbal[ti] AND learning[ti] AND tasks[ti] AND games[au]"
    assert xs.apa_double_slash("10.1037/0033-295X.87.6.532") == "10.1037//0033-295x.87.6.532"
    assert xs.apa_double_slash("10.1038/319774a0") is None


# --------------------------------------------------------------------------
# Cache: repeats make zero requests; the main cache is never written


def test_offline_repeat_uses_cache_and_refuses_network(tmp_path):
    main = Cache(tmp_path / "main.sqlite3")
    url = "https://api.crossref.org/works/10.1038%2F319774a0"
    main.save_response(dumps([url, {}, False]), {"url": url, "retrieved_at": "2026-09-23", "http_status": 200,
                                                 "body": {"status": "ok", "message": MORRIS_1986}})
    main.close()
    before = (tmp_path / "main.sqlite3").read_bytes()
    client = xs.make_client(tmp_path / "own.sqlite3", tmp_path / "main.sqlite3", contact="a@b.org", offline=True)
    assert xs.crossref_candidate(client, "10.1038/319774a0")["doi"] == "10.1038/319774a0"
    assert client.cache.hits["main"] == 1 and client.requests == 0
    assert xs.crossref_candidate(client, "10.1038/319774a0")  # now from the own cache
    assert client.cache.hits["own"] == 1
    with pytest.raises(ProviderError):
        xs.crossref_candidate(client, "10.1038/nature08002")
    assert (tmp_path / "main.sqlite3").read_bytes() == before
    client.cache.close()
