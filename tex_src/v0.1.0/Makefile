.PHONY: all clean

BIBTEX ?= bibtex

all:
	pdflatex -interaction=nonstopmode -halt-on-error main.tex
	$(BIBTEX) main
	pdflatex -interaction=nonstopmode -halt-on-error main.tex
	pdflatex -interaction=nonstopmode -halt-on-error main.tex

clean:
	rm -f main.aux main.bbl main.blg main.log main.out main.toc main.lot main.lof main.fls main.fdb_latexmk main.pdf
