from helpers import check_bib, compare_bibs
from argparse import ArgumentParser
import sys



def main():
    parser = ArgumentParser()
    parser.add_argument('-v', '--verify', type=str, nargs=1, help='check a .bib file for errors')
    parser.add_argument('-c', '--compare', type=str, nargs=2, help='compare the entries in two .bib files')
    parser.add_argument('-o', '--output', type=str, nargs=1, help='specify .bib file to output results to')
    parser.add_argument('-q', '--quiet', help='suppress output', action='store_true')
    parser.add_argument('-a', '--autofix', type=str, nargs=1, help='(USE WITH CAUTION!) attempt to automatically fix errors in .bib file')

    args = parser.parse_args(sys.argv)

    if args.verify:
        assert not args.compare, 'cannot use verify and compare flags simultaneously'
        
        if args.autofix:
            autofix = True
        else:
            autofix = False
        
        errors, corrected = check_bib(args.verify, autofix=autofix, outfile=args.output, verbose=!args.quiet)
        
        if len(errors) == 0:
            print('Congrats!  File looks OK.')
        else:
            raise Exception(f'{len(errors)} found in {args.verify}; check log for details.')
    elif args.compare:
        compare_bibs(args.compare[0], args.compare[1], outfile=args.output, verbose=!args.quiet)



