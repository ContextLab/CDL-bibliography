from helpers import check_bib

errors, corrected = check_bib('cdl.bib')
assert len(errors) == 0, 'check failed!'
