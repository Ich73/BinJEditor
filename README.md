# BinJ Editor
BinJ Editor lets you import, edit, save, share and export translations for games using the `.binJ` and `.e` formats to store messages. Those games include _Dragon Quest Monsters: Terry's Wonderland 3D_ and _Dragon Quest Monsters 2: Cobi and Tara's Marvelous Mysterious Key_.

![Screenshot](https://user-images.githubusercontent.com/44297391/91449697-b562e480-e87b-11ea-983f-1c6407ecef3a.png)


## Using BinJ Editor
You can download the newest version as an executable from the [Release Page](https://github.com/Ich73/BinJEditor/releases/latest). Extract the archive and run `BinJEditor.exe`.  
  
To import a file choose `File > Import...` and select the file. This process may take a few seconds. Now you can start editing the file by entering text into the last column. When you finished editing you can save a project file by choosing `File > Save As...` or export an edited `.binJ` or `.e` file by choosing `File > Export...`.
  
More information can be found in the [Wiki](https://github.com/Ich73/BinJEditor/wiki).

If you cannot start BinJ Editor on Windows 7, have a look at [this answer](https://github.com/pyinstaller/pyinstaller/issues/4706#issuecomment-633586051). Additionally you may want to install [Python 3.8](https://www.python.org/downloads/release/python-383/).


## For Developers
### Setup
This program is written using [Python 3.8](https://www.python.org/downloads/release/python-383/). You can install the required packages with the following commands.
```
python -m pip install pyqt5>=5.15.0
python -m pip install pyperclip>=1.8.0
```
Addionally you need `lrelease`, a Qt tool for converting `.ts` translation files to `.qm` files.  

### Compiling Resources
To convert the translation files and pack them with the other resources into a single `Resources.py` file, you can run the following commands. This is needed whenever you change any resource file.
```
pylupdate5 BinJEditor.pyw Resources/Forms/window.ui Resources/Forms/ftpclient.ui -ts -noobsolete Resources/i18n/de.ts
lrelease Resources/i18n/de.ts

pylupdate5 BinJEditor.pyw Resources/Forms/window.ui Resources/Forms/ftpclient.ui -ts -noobsolete Resources/i18n/en.ts
lrelease Resources/i18n/en.ts

pylupdate5 BinJEditor.pyw Resources/Forms/window.ui Resources/Forms/ftpclient.ui -ts -noobsolete Resources/i18n/es.ts
lrelease Resources/i18n/es.ts

lrelease Resources/i18n/qtbase_de.ts
lrelease Resources/i18n/qtbase_en.ts
lrelease Resources/i18n/qtbase_es.ts

pyrcc5 Resources.qrc -o Resources.py
```

### Running
You can run the program by using the command `python BinJEditor.pyw`.

### Distributing
To pack the program into a single executable file, [pyinstaller](http://www.pyinstaller.org/) is needed. Simply run the command `pyinstaller BinJEditor.spec --noconfirm` and the executable will be created in the `dist` folder.
