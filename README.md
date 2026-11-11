# OCR Text Finder (Windows 10 / 11)

Desktop programma: **WIN + SHIFT + S** bilen ekrandan bir ýeri kesýärsiňiz → EasyOCR tekst okaýar →
`data/text.txt` faýlyndaky **ähli** sözlemlerden gabat gelýänleri aýry-aýry görkezýär. Django ýok, Tkinter (Python bilen gelýär).

## Işletmek (Python bilen)
1. Python 3.11+ guruň (https://www.python.org/downloads/ , "Add python.exe to PATH" belläň).
2. `setup_and_run.bat` faýlyna iki gezek basyň. Birinji gezek internet gerek (PyTorch CPU, EasyOCR we OCR modelleri ýüklenýär).
3. Indiki gezeklerde `run.bat`.

## .exe ýasamak
`build_exe.bat` faýlyny işlediň → netije: `dist\OCRTextFinder\OCRTextFinder.exe`
(modeller bilelikde goşulýar, şonuň üçin .exe internetsiz hem işleýär). Bütin `OCRTextFinder` bukjasyny göçürseňiz bolýar.
`data\text.txt` faýlyny .exe-niň ýanynda üýtgedip bilersiňiz.

## Nähili işleýär
* Programma `WIN+SHIFT+S`-i **kesmeýär** – Windows-yň öz gurallary işleýär; programma diňe buferde (clipboard) täze surat peýda bolanda ony okaýar. Admin hukugy gerek däl.
* Menýu: **Dashboard** (netije), **History** (gözleg, görmek, pozmak), **Settings** (text.txt ýoly, Mode A/B, dil, ş.m.).
* Mode A – sözlemde OCR-daky ähli manyly sözler bolmaly; Mode B – iň bolmanda biri.
* Sözler doly söz hökmünde deňeşdirilýär (kiçi/uly harp we punktuasiýa hasaba alynmaýar); gaýtalanýan sözlemler bir gezek görkezilýär.
* `text.txt` bir gezek bölünýär we keşlenýär; faýl üýtgände awtomatiki täzeden okalýar.
* Faýllar: `finder.db` (SQLite), `screenshots/`, `settings.json`, `app.log`, `models/`.

## Sorag → jogap (Answer paneli)
Skrinşotda sorag ýa-da sözlem bolsa (meselem `Türkmenistanyň paýtagty nire?`), programma `text.txt` içinden iň laýyk sözlemi
(`Türkmenistanyň paýtagty Aşgabat şäheridir.`) **"Answer from text.txt"** panelinde uly harplar bilen görkezýär.
* Sözleriň ýeke-täk bolşy däl, **yzygiderligi we ýanaşyklygy** hem hasaba alynýar; seýrek sözler has agyr bahalanýar.
* Soraglyk sözler (nire, näme, haýsy, kim, haçan, ...) hasaba alynmaýar.
* Diakritika (ň, ý, ä, ş, ç, ž, ö, ü) deňeşdirilende hasaba alynmaýar, goşulmalar (Türkmenistan ≈ Türkmenistanyň) we 1 harplyk OCR säwlikleri çydanýar.
* Settings: "Answers to show" (näçe jogap) we "Minimum word coverage" (iň az gabat gelmeli sözler %).
* Türkmen harplary üçin Settings → OCR languages: `tr,en` (täze gurnamada standart). Köne gurnamada `tr,en` ýazyp "Save settings" basyň (birinji gezek täze model ýüklenýär).
* `text.txt` faýlyny **UTF-8** görnüşinde saklaň.

## Gurluş
`finder/services/`: `ocr_engine.py`, `screenshot_capture.py`, `text_processor.py`, `sentence_matcher.py`, `clipboard_monitor.py`;
`finder/`: `database.py`, `pipeline.py` (modullary birleşdirýär), `gui.py`, `config.py`.

## Test
`python -m unittest discover -s tests -v`
