"""Tests for bibcheck/research_quotes.py (the research validator's quote matching, which
research_route uses to re-check saved approvals).

Copied from tests/test_research_validate.py, which tests the whole validator
(verification/research-pilot-2026-09-24/validate.py, including its HTTP fetching) and lives
with it on the archive branch verification-records-2026-09; the fetching tests stay there.
Values and quotes are copied verbatim from the research batch files named on each case
(frozen here). Each normalisation rule has a positive case that the validator used to
reject although the quote supports the value, and a negative control where the value
really differs. No file or network is read.
"""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import research_quotes as V  # noqa: E402


def ok(field, value, quotes):
    return V.value_supported(field, value, quotes)


# --- 1. PNAS "USA" (wave6 batch-048) --------------------------------------------------------

PNAS = "Proceedings of the National Academy of Sciences, {USA}"


def test_pnas_usa_spelled_out():  # AmarEtal10
    assert ok("journal", PNAS, ["JT  - Proceedings of the National Academy of Sciences of the United States of America"]) == (True, [])


def test_pnas_usa_dotted():
    assert ok("journal", PNAS, ["Proceedings of the National Academy of Sciences of the U.S.A."]) == (True, [])


def test_pnas_usa_negative_control():
    # 'United States' without 'of America', or bare 'U.S.', is not the same abbreviation.
    assert ok("journal", PNAS, ["Proceedings of the National Academy of Sciences of the United States"])[1] == ["usa"]
    assert ok("journal", PNAS, ["Proceedings of the National Academy of Sciences, U.S."])[1] == ["usa"]
    assert ok("title", "Crime in the {USA}", ["Crime in the United States of America"])[1] == ["usa"]  # journals only


# --- 2. Journal series (wave6 batch-046) ----------------------------------------------------

PHIL_B = "Philosophical Transactions of the Royal Society of London Series {B}: Biological Sciences"


def test_series_letter_after_same_word():  # Colt83, Crai83
    quote = '"container-title":["Philosophical Transactions of the Royal Society of London. B, Biological Sciences"]'
    assert ok("journal", PHIL_B, [quote]) == (True, [])


def test_series_abbreviated_ser():
    assert ok("journal", PHIL_B, ["Philosophical Transactions of the Royal Society of London, Ser. B, Biological Sciences"]) == (True, [])


def test_series_negative_controls():
    # ValdEtal05: the quote has no 'of London', so neither word is evidenced.
    quote = '"container-title":["Philosophical Transactions of the Royal Society B: Biological Sciences"]'
    assert ok("journal", PHIL_B, [quote])[1] == ["london", "series"]
    # A different series letter is a different journal.
    assert ok("journal", PHIL_B, ["Philosophical Transactions of the Royal Society of London. A, Biological Sciences"])[1] == ["series"]


# --- 3. Names: JSON escapes, umlaut transliteration, apostrophes (wave6 batch-046) -----------

def test_crossref_json_escapes_in_names():  # DeusEtal06
    value = 'G Deuschl and H Sch{\\"a}fer and K B\\"{o}tzel and A Deutschl\\"{a}nder'
    quotes = ['"given":"G\\u00fcnther","family":"Deuschl"', '"given":"Helmut","family":"Sch\\u00e4fer"',
              '"given":"Kai","family":"B\\u00f6tzel"', '"given":"Angela","family":"Deutschl\\u00e4nder"']
    assert ok("author", value, quotes) == (True, [])


def test_json_escape_c_acute():  # TownFifi04
    assert ok("author", "J T Townsend and M Fifi{\\'c}",
              ['"given":"James T.","family":"Townsend"', '"given":"Mario","family":"Fifi\\u0107"']) == (True, [])


def test_hyphenated_spanish_surnames():  # ValdEtal05
    value = "P A Vald\\'{e}s-Sosa and J M S\\'{a}nchez-Bornot and L Melie-Garc\\'{i}a"
    quotes = ['"given":"Pedro A","family":"Vald\\u00e9s-Sosa"', '"given":"Jose M","family":"S\\u00e1nchez-Bornot"',
              '"given":"Lester","family":"Melie-Garc\\u00eda"']
    assert ok("author", value, quotes) == (True, [])


def test_names_negative_control():
    quotes = ['"given":"Mario","family":"Fifi\\u0107"']
    assert ok("author", "M Fific and J Smith", quotes)[1] == ["smith"]
    assert ok("author", "M Fific-Jones", quotes)[1] == ["fific-jones"]


def test_umlaut_transliteration_both_ways():
    # Value umlaut, quote 'ae' (the old rule) and value 'ae', quote umlaut (new).
    assert ok("author", 'H Sch{\\"a}fer', ["Helmut Schaefer"]) == (True, [])
    assert ok("author", "H Schaefer", ['"family":"Sch\\u00e4fer"']) == (True, [])
    # Negative control: a plain 'a' is not an umlaut.
    assert ok("author", "H Schaefer", ["Helmut Schafer"])[1] == ["schaefer"]


def test_apostrophe_lookalike_acute():  # CoheEtal96: Crossref prints O´Reilly
    assert ok("author", "J D Cohen and T S Braver and R C O'Reilly",
              ['"given":"Jonathan D.","family":"Cohen"', '"given":"Todd S.","family":"Braver"',
               '"given":"Randall","family":"O\\u00b4Reilly"']) == (True, [])
    assert ok("author", "R C O'Reilly", ["Randall O’Reilly"]) == (True, [])


def test_apostrophe_negative_control():
    assert ok("author", "R C O'Reilly", ['"family":"Reilly"'])[1] == ["o'reilly"]


# --- 4. Titles, volume (wave6 batch-046/051/052) ----------------------------------------------

def test_json_escaped_curly_quotes_in_title():  # TurnBrai15
    value = "Unravelling the `safe' concept in teaching: what can we learn from teachers' understanding?"
    quote = "Unravelling the \\u2018Safe\\u2019 concept in teaching: what can we learn from teachers\\u2019 understanding?"
    assert ok("title", value, [quote]) == (True, [])


def test_times_symbol():  # Flex81
    value = "Homogenizing the $2 \\times 2$ contingency table: a method for removing dependencies due to subject and item differences"
    quote = ('"title":["Homogenizing the 2\\u2002\\u00d7\\u20022 contingency table: A method for removing '
             'dependencies due to subject and item differences."]')
    assert ok("title", value, [quote]) == (True, [])


def test_json_escaped_quote_mark_is_not_an_umlaut():  # Hint86
    value = "``{S}chema abstraction'' in a multiple-trace memory model"
    quote = '"title":["\\"Schema abstraction\\" in a multiple-trace memory model."]'
    assert ok("title", value, [quote]) == (True, [])
    assert V.delatex('\\"{o}') == "ö" and V.delatex('B\\"otzel') == "Bötzel"  # real umlauts still work


def test_title_negative_controls():
    quote = '"title":["\\"Schema abstraction\\" in a multiple-trace memory model."]'
    assert ok("title", "Schema abstractions in a multiple-trace memory model", [quote])[1] == ["abstractions"]
    # Sten95: the proceedings index misspells the title ('Replannig'); that does not evidence 'replanning'.
    assert ok("title", "The focussed {D}* algorithm for real-time replanning",
              ["The Focussed D&quot; Algorithm for Real-Time Replannig", "is the efficiency of the Focussed D* algorithm"])[1] == ["replanning"]


def test_roman_volume():  # Skag25
    assert ok("volume", "34", ['"vol. XXXIV, no. 8; whole no. 161, 1925"']) == (True, [])


def test_roman_volume_negative_controls():
    assert ok("volume", "35", ['"vol. XXXIV, no. 8; whole no. 161, 1925"'])[1] == ["35"]
    assert ok("volume", "4", ["Chapter IV of the book"])[1] == ["4"]  # only after 'vol.'/'volume'
    assert V.roman_to_int("iiii") is None and V.roman_to_int("xxxiv") == 34


# --- 5. Trademark signs and math subscripts (wave7 batch-063/064) -----------------------------

def test_trademark_symbols():  # GusmEtal14
    value = ("Comparison of {FitBit}{\\textregistered} {Ultra} to {ActiGraph}{\\texttrademark} {GT1M} for assessment "
             "of physical activity in young adults during treadmill walking")
    quote = ("Comparison of FitBit® Ultra to ActiGraph™ GT1M for Assessment of Physical Activity in Young Adults "
             "During Treadmill Walking")
    assert ok("title", value, [quote]) == (True, [])
    assert ok("title", "Comparison of {FitBit}{\\textregistered} {Charge} to {ActiGraph}", [quote])[1] == ["charge"]


def test_math_subscript():  # TeppEtal95
    value = ("{GABA$_A$} receptor-mediated inhibition of rat substantia nigra dopaminergic neurons by pars "
             "reticulata projection neurons")
    quote = ("GABAA receptor-mediated inhibition of rat substantia nigra dopaminergic neurons by pars reticulata "
             "projection neurons")
    assert ok("title", value, [quote]) == (True, [])
    assert V.delatex("{GABA$_{B}$}") == "GABAB"
    assert ok("title", "{GABA$_B$} receptor-mediated inhibition", [quote])[1] == ["gabab"]


def test_quote_matching_still_exact_after_json_unescape():
    page = '{"family":"Sch\\u00e4fer","given":"Helmut"}'
    assert V.norm('"family":"Schäfer"') in V.norm(page)
    assert V.norm('"family":"Schafer"') not in V.norm(page)


# --- 7. Wave-7 gaps (research wave 7) ---------------------------------

def test_plus_minus_macro():  # LismIdia95, batch-058 (PubMed title)
    value = "Storage of $7\\pm2$ short-term memories in oscillatory subcycles"
    assert ok("title", value, ["Storage of 7 +/- 2 short-term memories in oscillatory subcycles"]) == (True, [])
    assert V.norm("7 ± 2") == V.norm("7 +/- 2")
    # negative control: a different word is still missing
    assert ok("title", value, ["Storage of 7 +/- 2 long-term memories in oscillatory subcycles"]) == (False, ["short"])


def test_camel_case_run_in_titles():  # Howa18, KahaEtal99b, batch-065 (PubMed XML ArticleTitle)
    assert ok("title", "Memory as perception of the past: compressed time in mind and brain",
              ["Memory as Perception of the Past: Compressed Time inMind and Brain."]) == (True, [])
    assert ok("title", "Using intracranial recordings to study theta. {R}esponse to {J. O'Keefe} and {N. Burgess} (1999)",
              ["Using intracranial recordings to study thetaResponse to J. O'Keefe and N. Burgess (1999)."]) == (True, [])


def test_camel_case_run_in_surname_particle():  # MillEtal07c, batch-071 (PubMed 'denNijs')
    value = "K J Miller and M {den Nijs} and P Shenoy and J W Miller and R P N Rao and J G Ojemann"
    assert ok("author", value, ["Kai J Miller, Marcel denNijs, Pradeep Shenoy",
                                "John W Miller, Rajesh P N Rao, Jeffrey G Ojemann"]) == (True, [])


def test_camel_case_negative_controls():
    # 'McDonald' / 'DiCarlo' are not split: one capital-led syllable is not a run-in word
    assert ok("author", "A Donald", ["J McDonald"]) == (False, ["donald"])
    assert ok("author", "J Carlo", ["J J DiCarlo"]) == (False, ["carlo"])
    # an all-lowercase join is not split either
    assert ok("title", "study theta response", ["study thetaresponse"]) == (False, ["theta", "response"])


def test_german_ordinal_volume():  # MullSchu94, batch-066 (archive.org djvu title page)
    assert ok("volume", "6", ["Sechster  Band."]) == (True, [])
    assert ok("volume", "12", ["Zwölfter Band"]) == (True, [])


def test_german_ordinal_volume_negative_controls():
    assert ok("volume", "7", ["Sechster  Band."]) == (False, ["7"])
    assert ok("volume", "6", ["Sechster Heft"]) == (False, ["6"])  # Heft is an issue, not a volume
    assert ok("volume", "6", ["der sechste Versuch"]) == (False, ["6"])


def test_line_break_hyphenation_in_value_words():  # Rans02 title, batch-066 (djvu OCR)
    value = ("Ueber {Hemmung} gleichzeitiger {Reizwirkungen}: experimenteller {Beitrag} zur {Lehre} "
             "von den {Bedingungen} der {Aufmerksamkeit}")
    quotes = ["Ueber Hemmung gleichzeitiger Reizwirkungen. 75",
              "Experimenteller Beitrag zur Lehre von den Be- \ndingungen der Aufmerksamkeit"]
    assert ok("title", value, quotes) == (True, [])
    # negative control: joining a hyphenated word does not invent a different word
    assert ok("title", "Bedingungen", ["Be- \nstimmungen"]) == (False, ["bedingungen"])


def test_hyphen_break_written_as_space_in_quote():  # Niph78, batch-065 (djvu 'Dis-\ntribution')
    page = ('Mr.  Nipher  made  the  following  communication  tkOn  the  Dis- \ntribution  of  '
            'Errors  in  Numbers  Written  from  Memory"  :  \n\nIn  writing')
    quote = 'communication tkOn the Dis- tribution of Errors in Numbers Written from Memory'
    assert V.hyphen_joined(V.norm(quote)) in V.hyphen_joined(V.norm(page))
    assert ok("title", "On the distribution of errors in numbers written from memory", [quote]) == (True, [])
    # negative control: a different word after the hyphen is still a miss
    assert V.hyphen_joined(V.norm("the Dis- position of Errors")) not in V.hyphen_joined(V.norm(page))


def test_escaped_underscore_in_titles():  # ChanEtal20, MuelEtal18, batch-066 (DataCite)
    assert ok("title", "{naturalistic-data-analysis/naturalistic\\_data\\_analysis}: {Version 1.0}",
              ['"title":"naturalistic-data-analysis/naturalistic_data_analysis: Version 1.0"']) == (True, [])
    assert ok("title", "{amueller/word\\_cloud}: {WordCloud} 1.5.0",
              ['"title":"amueller/word_cloud: WordCloud 1.5.0"']) == (True, [])
    # negative control: an underscore is not a space
    assert ok("title", "{amueller/word\\_cloud}", ['"title":"amueller/word cloud"']) == (False, ["word_cloud"])


def test_accent_on_dotless_i():  # BlanEtal08a, BaboEtal11, batch-070
    assert V.delatex('na{\\"\\i}ve') == "naïve" and V.delatex("Cad{\\'\\i}k") == "Cadík"
    assert ok("title", 'The {Berlin} brain-computer interface: accurate performance from first-session in {BCI}-na{\\"\\i}ve subjects',
              ["The Berlin Brain-Computer Interface: Accurate performance from first-session in BCI-naive subjects"]) == (True, [])
    assert ok("author", "L Baboud and M {\\v C}ad{\\'\\i}k and E Eisemann and H-P Seidel",
              ['"given":"Lionel","family":"Baboud"', '"given":"Martin","family":"Cadik"',
               '"given":"Elmar","family":"Eisemann"', '"given":"Hans-Peter","family":"Seidel"',
               '"familyName":"Čadík"']) == (True, [])
    # negative control: a JSON-escaped quote mark before ' in' is still not an umlaut
    assert V.delatex('said \\" in') == 'said \\" in'


EJN = "{European} Journal of Neuroscience"


def test_journal_table_abbreviation():  # BartEtal11a ... GaynEtal08, batch-069 (MEDLINE TA line)
    assert "eur j neurosci" in V.journal_abbreviations(EJN)
    assert ok("journal", EJN, ["TA  - Eur J Neurosci"]) == (True, [])
    assert ok("journal", EJN, ["Eur. J. Neurosci."]) == (True, [])


def test_journal_table_abbreviation_negative_controls():
    # a different journal's abbreviation, and one nested inside another journal's name
    assert ok("journal", EJN, ["TA  - J Neurosci"])[0] is False
    assert ok("journal", "The Journal of Neuroscience", ["TA  - Eur J Neurosci"])[0] is False
    assert ok("journal", "The Journal of Neuroscience", ["TA  - J Neurosci"]) == (True, [])
    # an arbitrary abbreviation that is not in the table does not count
    assert ok("journal", EJN, ["Europ. Jour. Neurosc."])[0] is False
    # table aliases that are not abbreviations of the target (renamings) are not used
    assert not V.abbreviates("annual reviews in neuroscience".split(), "annual review of neuroscience".split())
    assert not V.abbreviates("j neurosci".split(), "european journal of neuroscience".split())


def test_publisher_same_firm_catalogue_forms():  # Keme72, Semo21, Semo23, Wood38, Addi02, LaddWood11 (batch-075)
    assert ok("publisher", "Charles Scribner's Sons", ["Scribner"]) == (True, [])
    assert ok("publisher", "Charles Scribner's Sons", ["C. Scribner's Sons,"]) == (True, [])
    assert ok("publisher", "George, Allen, and Unwin", ["G. Allen & Unwin ltd.;"]) == (True, [])
    assert ok("publisher", "George, Allen, and Unwin", ["G. Allen & Unwin, ltd."]) == (True, [])
    assert ok("publisher", "Henry Holt and Company", ["H. Holt and company"]) == (True, [])
    assert ok("publisher", "Institute of Physics Publishing", ["Institute of Physics Pub."]) == (True, [])


def test_publisher_same_firm_negative_controls():
    assert ok("publisher", "Henry Holt and Company", ["Holt, Rinehart and Winston"])[0] is False
    assert ok("publisher", "Institute of Physics Publishing", ["Institute of Physics"])[0] is False
    assert ok("publisher", "George, Allen, and Unwin", ["Unwin Hyman"])[0] is False
    # a firm not in the catalogue gets no short form
    assert ok("publisher", "Harper and Brothers", ["Harper"])[0] is False


# The body lx2.loc.gov:210 returned for LaddWood11's LCCN query (cached 2026-09-25), verbatim.
SRU_DIAGNOSTIC = ('<?xml version="1.0"?>\n<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
                  '<zs:version>1.1</zs:version><zs:numberOfRecords>1</zs:numberOfRecords><zs:echoedSearchRetrieveRequest>'
                  '<zs:version>1.1</zs:version><zs:query>bath.lccn=11013120</zs:query><zs:maximumRecords>1</zs:maximumRecords>'
                  '<zs:recordPacking>xml</zs:recordPacking><zs:recordSchema>marcxml</zs:recordSchema></zs:echoedSearchRetrieveRequest>'
                  '<zs:diagnostics xmlns:diag="http://www.loc.gov/zing/srw/diagnostic/"><diag:diagnostic>'
                  '<diag:uri>info:srw/diagnostic/1/61</diag:uri><diag:details></diag:details>'
                  '<diag:message>First record position out of range</diag:message></diag:diagnostic></zs:diagnostics>'
                  '</zs:searchRetrieveResponse>')
SRU_RECORD = ('<?xml version="1.0"?>\n<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
              '<zs:version>1.1</zs:version><zs:numberOfRecords>1</zs:numberOfRecords><zs:records><zs:record>'
              '<zs:recordData><record xmlns="http://www.loc.gov/MARC21/slim"><datafield tag="245" ind1="1" ind2="0">'
              '<subfield code="a">Elements of physiological psychology;</subfield></datafield></record></zs:recordData>'
              '</zs:record></zs:records></zs:searchRetrieveResponse>')


def test_sru_diagnostic_is_transient():
    assert "First record position out of range" in V.transient_error(SRU_DIAGNOSTIC)
    assert V.transient_error(SRU_RECORD) is None
    assert V.transient_error("<html>a page that mentions a diagnostic test</html>") is None


# --- wave 8/9 validator gaps (verbatim quotes from wave8/wave9 batch files) ------------------

def test_house_proceedings_word():  # MallEtal97, ParkEtal24, DolfWend98 (batch-096)
    assert ok("booktitle", "Proceedings of the International Conference on Artificial Neural Networks",
              ['citation_conference_title" content="International Conference on Artificial Neural Networks"']) == (True, [])
    assert ok("booktitle", "Proceedings of the International Conference on Machine Learning",
              ['citation_conference_title" content="International Conference on Machine Learning"']) == (True, [])
    assert ok("booktitle", "Proceedings of the International Conference on Spoken Language Processing",
              ["5th International Conference on Spoken Language Processing (ICSLP 1998)"]) == (True, [])


def test_house_proceedings_word_negative_controls():
    # never stands in for a missing content word: the whole missing list is reported
    assert ok("booktitle", "Proceedings of the International Conference on Machine Learning",
              ["International Conference on Learning Representations"]) == (False, ["proceedings", "machine"])
    # only as the opening 'Proceedings of': elsewhere it is a content word
    assert ok("booktitle", "Annual Proceedings of Cognition", ["Annual Meeting of Cognition"])[0] is False
    # and only in a booktitle
    assert ok("title", "Proceedings of the Workshop", ["Workshop"])[0] is False


SFN_FOOTER = "2009 Neuroscience Meeting Planner. Chicago, IL: Society for Neuroscience, 2009"


def test_sfn_house_booktitle():  # MannEtal09b ... vanVEtal05 (batch-097)
    assert ok("booktitle", "Society for Neuroscience Abstracts", [SFN_FOOTER]) == (True, [])
    assert ok("booktitle", "Society for Neuroscience Abstracts",
              ["Neuroscience 2005 Abstract",
               "2005 Neuroscience Meeting Planner. Washington, DC : Society for Neuroscience, 2005"]) == (True, [])


def test_sfn_house_booktitle_negative_controls():
    # the organisation must be quoted as a phrase, not its words scattered
    assert ok("booktitle", "Society for Neuroscience Abstracts",
              ["Neuroscience 2005 Abstract", "Society meeting"])[0] is False
    # only the SfN house form carries the added word
    assert ok("booktitle", "Cognitive Neuroscience Society Abstracts", ["Cognitive Neuroscience Society"])[0] is False
    assert ok("title", "Society for Neuroscience Abstracts", [SFN_FOOTER])[0] is False


def test_affiliation_digits_on_surnames():  # ChenEtal15a (batch-079), LongKaha12a (batch-094)
    assert ok("author", "P-H Chen and J Chen and Y Yeshurun and U Hasson and J V Haxby and P J Ramadge",
              ["Po-Hsuan Chen1 , Janice Chen2 , Yaara Yeshurun2 , Uri Hasson2 , James V. Haxby3 , Peter J. Ramadge1"]) == (True, [])
    assert ok("author", "N M Long and M J Kahana", ["Long1, Michael J Kahana1", "Nicole"]) == (True, [])


def test_affiliation_digits_negative_controls():
    # only author/editor fields, and only digits after the word, not a different name
    assert ok("title", "Chen", ["Chen1"])[0] is False
    assert ok("author", "J Chen", ["Janice Cheng2"]) == (False, ["chen"])
    assert ok("author", "J Chen", ["J Che1n"]) == (False, ["chen"])


def test_dotted_initialism():  # Whor56 (batch-078, archive.org metadata)
    assert ok("publisher", "{MIT} Press", ['"publisher":"Cambridge, Mass. : M.I.T. Press"']) == (True, [])


def test_dotted_initialism_negative_controls():
    assert ok("publisher", "{MIT} Press", ["M.I. Press"])[0] is False
    assert ok("publisher", "{MIT} Press", ["M. I. T. Press"])[0] is False  # spaced initials are not joined


def test_single_capital_run_in():  # BrowMcCo06 (batch-080, Crossref title+subtitle joined)
    assert ok("title", "The role of time in human memory and binding: a review of the evidence",
              ["The role of time in human memory and bindingA review of the evidence"]) == (True, [])


def test_single_capital_run_in_negative_control():
    assert ok("title", "binding a review", ["bindinga review"])[0] is False
    assert ok("author", "J Carlo", ["J J DiCarlo"]) == (False, ["carlo"])


def test_volume_abbreviated_in_contents_note():  # McClEtal86, RumeEtal86a (batch-078, LoC 505)
    t = "Parallel distributed processing: explorations in the microstructure of cognition, volume 2: psychological and biological models"
    q = ["Parallel distributed processing : explorations in the microstructure of cognition /",
         "v. 1. Foundations -- v. 2. Psychological and biological models."]
    assert ok("title", t, q) == (True, [])
    assert ok("title", t.replace("volume 2: psychological and biological models", "volume 1: foundations"), q) == (True, [])


def test_volume_abbreviated_negative_controls():
    t = "Parallel distributed processing, volume 3: foundations"
    assert ok("title", t, ["Parallel distributed processing", "v. 1. Foundations"]) == (False, ["volume"])
    assert ok("title", "A handbook, volume 2", ["A handbook 2"]) == (False, ["volume"])
    assert ok("title", "The volume of the brain", ["The v. of the brain"]) == (False, ["volume"])


def test_value_words_run_together():  # BartEtal04c (batch-096, UMass publication list)
    assert ok("address", "La Jolla, {CA}", ["International Conference on Developmental Learning (ICDL), LaJolla, CA, USA"]) == (True, [])


def test_value_words_run_together_negative_controls():
    assert ok("address", "La Jolla, {CA}", ["LaJollan, CA"])[0] is False
    assert ok("address", "New York", ["NewYorker"])[0] is False
    assert ok("address", "Jolla", ["LaJolla"])[0] is False  # no preceding value word to join


def test_publisher_sage_catalogue_form():  # SnijBosk12 (batch-090, LoC 260$b)
    assert ok("publisher", "{SAGE} Publications", ['<subfield code="b">Sage,</subfield>']) == (True, [])
    assert ok("publisher", "{SAGE} Publications", ["Sagebrush Press"])[0] is False
