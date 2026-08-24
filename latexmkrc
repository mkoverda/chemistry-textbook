@default_files = ('main.tex');

$pdf_mode = 1;

$out_dir     = '.';
$aux_dir     = 'build';
$emulate_aux = 1;

$pdflatex = 'pdflatex -synctex=1 -interaction=nonstopmode -file-line-error %O %S';
$makeindex = 'texindy -L russian -C utf8 -o %D %S';