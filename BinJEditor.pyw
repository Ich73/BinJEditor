""" Author: Dominik Beese
>>> BinJ Editor
	An editor for .binJ and .e files with custom decoding tables.
<<<
"""

# pip install pyqt5
# pip install pyperclip
from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QInputDialog, QDialog, QMessageBox, QAbstractItemView, QTableWidgetItem, QPushButton, QActionGroup, QAction, QItemDelegate, QPlainTextEdit, QStyle
from PyQt5.QtCore import QTranslator, QLocale, QRegExp, QTimer, QFile, QEvent, Qt
from PyQt5.QtGui import QRegExpValidator, QIntValidator, QPixmap, QIcon, QFont, QTextCursor
from JTools import *
import Resources
import pyperclip as clipboard
import json
import re
import sys
import os
from os import path, linesep
from shutil import copyfile
from zipfile import ZipFile
from gzip import GzipFile
from tempfile import gettempdir as tempdir
from ftplib import FTP
import webbrowser
from urllib.request import urlopen

TABLE_FOLDER = 'Table'
CONFIG_FILENAME = 'config.json'

APPNAME = 'BinJ Editor'
VERSION = 'v2.0.0'
REPOSITORY = r'Ich73/BinJEditor'
AUTHOR = 'Dominik Beese 2020-2021'
SPECIAL_THANKS = 'Frank Colmines'


###########
## Setup ##
###########

# set paths
ROOT = path.dirname(path.realpath(sys.argv[0]))
TABLE_PATH = path.join(ROOT, TABLE_FOLDER)
CONFIG_FILE = path.join(ROOT, CONFIG_FILENAME)
try:
	# write and delete test file to check permissions
	temp = path.join(ROOT, 'temp')
	with open(temp, 'wb') as file: file.write(b'\x00')
	os.remove(temp)
except PermissionError:
	# use user path and appdata instead
	ROOT = path.expanduser('~') # user path
	DATA = path.join(os.getenv('APPDATA'), APPNAME) # appdata
	OLD_TABLE_PATH = TABLE_PATH
	TABLE_PATH = path.join(DATA, TABLE_FOLDER)
	CONFIG_FILE = path.join(DATA, CONFIG_FILENAME)
	if not path.exists(TABLE_PATH): os.makedirs(TABLE_PATH)
	# copy tables from executable path to appdata
	for table in os.listdir(OLD_TABLE_PATH):
		old_table = path.join(OLD_TABLE_PATH, table)
		new_table = path.join(TABLE_PATH, table)
		if not path.exists(new_table) or path.getmtime(old_table) > path.getmtime(new_table):
			copyfile(old_table, new_table)

# set windows taskbar icon
try:
	from PyQt5.QtWinExtras import QtWin
	appid = APPNAME.replace(' ', '').lower() + '.' + VERSION
	QtWin.setCurrentProcessExplicitAppUserModelID(appid)
except: pass

# config
class Config:
	cfg = None
	
	def loadConfig():
		if Config.cfg is not None: return
		if not path.exists(CONFIG_FILE):
			Config.cfg = dict()
			return
		try:
			with open(CONFIG_FILE, 'r') as file:
				Config.cfg = json.load(file)
		except:
			Config.cfg = dict()
	
	def saveConfig():
		with open(CONFIG_FILE, 'w') as file:
			json.dump(Config.cfg, file)
	
	def get(key, default = None):
		Config.loadConfig()
		value = Config.cfg.get(key)
		if value is None:
			Config.set(key, default)
			return default
		return value
	
	def set(key, value):
		Config.cfg[key] = value
		Config.saveConfig()


#####################
## Custom QWidgets ##
#####################

def createHex(bytes):
	""" Example: '\xa4\x08' -> 'A4 08' """
	return ' '.join(['%02X' % b for b in bytes])

def parseHex(s):
	""" Example: 'A4 08' -> '\xa4\x08' """
	s = ''.join(c for c in s if c in set('0123456789ABCDEFabcdef'))
	return bytes([int(s[i:i+2], 16) for i in range(0, len(s), 2)])

class DataTableWidgetItem(QTableWidgetItem):
	""" A QTableWidgetItem with a data attribute.
		Qt.EditRole & Qt.DisplayRole -> text
		Qt.UserRole -> data
	"""
	def data2text(self, data): pass
	def text2data(self, text): pass
	def dataLt(self, dataA, dataB): pass
	def __init__(self, data):
		super(DataTableWidgetItem, self).__init__(self.data2text(data))
		self._data = data
	def __lt__(self, other):
		if isinstance(other, QTableWidgetItem):
			return self.dataLt(self._data, other._data)
		return super(DataTableWidgetItem, self).__lt__(other)
	def setData(self, role = Qt.UserRole, data = None):
		if role in [Qt.EditRole, Qt.DisplayRole]:
			self._data = self.text2data(data)
			data = self.data2text(self._data)
		elif role == Qt.UserRole:
			self._data = data
			data = self.data2text(self._data)
		super(DataTableWidgetItem, self).setData(role, data)
	def data(self, role = Qt.UserRole):
		if role in [Qt.EditRole, Qt.DisplayRole]: return self.data2text(self._data)
		elif role == Qt.UserRole: return self._data
		return None

class IntTableWidgetItem(DataTableWidgetItem):
	""" A QTableWidgetItem with an int value.
		Overrides the __lt__ method for int instead of string value comparison.
	"""
	def data2text(self, data):
		return str(data)
	def text2data(self, text):
		return int(text)
	def dataLt(self, dataA, dataB):
		return dataA < dataB

class HexBytesTableWidgetItem(DataTableWidgetItem):
	""" A QTableWidgetItem for bytes representing a hex value.
		Overrides the __lt__ value comparison.
	"""
	def data2text(self, data):
		return createHex(data)
	def text2data(self, text):
		return parseHex(text)
	def dataLt(self, dataA, dataB):
		if not dataA and dataB: return False
		if dataA and not dataB: return True
		if len(dataA) != len(dataB): return len(dataA) < len(dataB)
		return dataA < dataB

class ListTableWidgetItem(DataTableWidgetItem):
	""" A QTableWidgetItem for a special list representing a text value.
		Overrides the __lt__ value comparison.
	"""
	def __init__(self, data, addLinebreaks = True):
		self.setAutomaticLinebreaksEnabled(addLinebreaks)
		super(ListTableWidgetItem, self).__init__(data)
	def setAutomaticLinebreaksEnabled(self, enabled):
		self.addLinebreaks = enabled
	def data2text(self, data):
		if self.addLinebreaks:
			t = ''
			for char in data:
				if isinstance(char, str): t += char # normal case
				else: # special case
					if t and char[0] in ['SEP', 'LF']: t += '\n' # extra linebreak before
					t += '[%s]' % char[0]
					if char[0] in ['SEP']: t += '\n' # extra linebreak after
			return t
		else: return list2text(data)
	def text2data(self, text):
		return text2list(text.replace('\n', ''))
	def dataLt(self, dataA, dataB):
		if not dataA and dataB: return False
		if dataA and not dataB: return True
		return list2text(dataA) < list2text(dataB)

class MultiLineItemDelegate(QItemDelegate):
	""" A QItemDelegate for entering multi-line text into a table cell. """
	def createEditor(self, parent, option, index):
		editor = QPlainTextEdit(parent)
		editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # disable both scrollbars
		editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		return editor
	def setEditorData(self, editor, index):
		self.originalText = index.data() # save text before editing
		if self.editorEvent == QEvent.KeyPress: editor.setPlainText('') # clear text if entered by key press
		else: editor.setPlainText(index.data()) # else insert text
		if editor.height() <= 24: editor.setLineWrapMode(QPlainTextEdit.NoWrap) # disable word wrap if single line text
		editor.moveCursor(QTextCursor.End) # move cursor to end of text
	def editorEvent(self, event, model, option, index):
		self.editorEvent = event.type()
		return False
	def setModelData(self, editor, model, index):
		model.setData(index, editor.toPlainText())
	def eventFilter(self, editor, event):
		if not editor or not event: return False
		if event.type() in [QEvent.KeyPress]:
			# Return/Enter -> enter linebreak OR close editor
			if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
				if event.modifiers() in [Qt.ShiftModifier, Qt.ControlModifier]:
					editor.insertPlainText('\n')
					return True
				else:
					self.commitData.emit(editor)
					self.closeEditor.emit(editor)
					return True
			# Escape -> restore original text, close editor
			elif event.key() == Qt.Key_Escape:
				editor.setPlainText(self.originalText)
				self.commitData.emit(editor)
				self.closeEditor.emit(editor)
				return True
		return super(QItemDelegate, self).eventFilter(editor, event)


############
## Window ##
############

class Window(QMainWindow):
	""" The Main Window of the editor. """
	
	def __init__(self, load_file = None):
		super(Window, self).__init__()
		uiFile = QFile(':/Resources/Forms/window.ui')
		uiFile.open(QFile.ReadOnly)
		loadUi(uiFile, self)
		uiFile.close()
		
		# key listener
		self.keysPressed = set()
		
		# state
		self.info = {
			'filename':      None, # the name of the currently loaded file
			'mode':          None, # the current mode ('binJ' or 'e')
			'decodingTable': None, # the current decoding table
			'SEP':  parseHex(Config.get('SEP', 'E31B')), # the current separator token
		}
		self.flag = {
			'changed': False, # whether the loaded data was edited
			'savable': False, # whether the current file can be saved without save as
			'loading': False, # while setData() is running
			'editing': False, # while some editing is done and tableCellChanged() should not run
		}
		self.cache = {
			'decodingTableFromSave': None, # the decoding table of the loaded save file
		}
		
		# data
		self.data = None # list of original bytes, original text, edited bytes, edited text
		self.extra = {
			# 'prefix': None, # the prefix bytes
		}
		
		# dialogs
		self.dialogs = list()
		
		# menu > file
		self.actionOpen.triggered.connect(self.openFile)
		self.actionOpen.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
		self.actionSave.triggered.connect(self.saveFile)
		self.actionSave.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
		self.actionSaveAs.triggered.connect(self.saveFileAs)
		self.actionSaveAs.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
		self.actionClose.triggered.connect(self.closeFile)
		self.actionClose.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
		self.actionImport.triggered.connect(self.importFile)
		self.actionImport.setIcon(self.style().standardIcon(QStyle.SP_ArrowLeft))
		self.actionExport.triggered.connect(self.exportFile)
		self.actionExport.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
		self.actionApplyPatch.triggered.connect(self.importPatch)
		self.actionCreatePatch.triggered.connect(self.exportPatch)
		
		# menu > edit
		self.menuDecodingTableGroup = QActionGroup(self.menuDecodingTable)
		self.menuDecodingTable.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
		self.menuDecodingTableGroup.addAction(self.actionDecodingTableFromSav) # table from save
		self.menuDecodingTableGroup.addAction(self.actionNoDecodingTable) # no table
		if not path.exists(TABLE_PATH): os.makedirs(TABLE_PATH) # create directory if missing
		for filename in [f for f in os.listdir(TABLE_PATH) if path.splitext(f)[1] == '.txt']:
			file = path.join(TABLE_PATH, filename)
			action = self.menuDecodingTable.addAction(filename)
			action.setData(file)
			action.setCheckable(True)
			self.menuDecodingTableGroup.addAction(action)
		self.menuDecodingTableGroup.triggered.connect(self.updateDecodingTable)
		self.updateDecodingTable(None) # select default
		self.actionGoToLine.triggered.connect(self.goToLine)
		self.actionGoToLine.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
		
		# menu > view
		self.actionHideEmptyTexts.setChecked(Config.get('hide-empty-texts', True))
		self.actionHideEmptyTexts.triggered.connect(lambda value: Config.set('hide-empty-texts', value))
		self.actionHideEmptyTexts.triggered.connect(self.filterData)
		self.actionScaleRowsToContents.setChecked(Config.get('scale-rows-to-contents', True))
		self.actionScaleRowsToContents.triggered.connect(lambda value: Config.set('scale-rows-to-contents', value))
		self.actionScaleRowsToContents.triggered.connect(self.resizeTable)
		
		# menu > tools
		self.actionFTPClient.triggered.connect(self.showFTPClient)
		self.actionFTPClient.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
		self.actionSearchDlg.triggered.connect(self.showSearchDlg)
		self.actionSearchDlg.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
		
		# menu > settings
		self.menuLanguageGroup = QActionGroup(self.menuLanguage)
		self.menuLanguageGroup.addAction(self.actionGerman)
		self.menuLanguageGroup.addAction(self.actionEnglish)
		self.menuLanguageGroup.addAction(self.actionSpanish)
		def retranslateUi(language):
			self.retranslateUi(language)
			for dlg in self.dialogs:
				dlg.retranslateUi()
		self.menuLanguageGroup.triggered.connect(retranslateUi)
		self.actionSeparatorToken.triggered.connect(self.editSeparatorToken)
		
		# menu > help
		self.actionAbout.triggered.connect(self.showAbout)
		self.actionAbout.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
		self.actionCheckForUpdates.triggered.connect(lambda: self.checkUpdates(True))
		self.actionCheckForUpdates.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
		
		# filter
		self.editFilter.setFixedWidth(280)
		self.editFilter.textChanged.connect(self.filterData)
		self.buttonFilter.setFixedWidth(20)
		self.buttonFilter.clicked.connect(self.editFilter.clear)
		
		# table
		self.table.setColumnCount(5)
		self.table.cellChanged.connect(self.tableCellChanged)
		self.table.cellDoubleClicked.connect(self.tableCellDoubleClicked)
		self.table.setItemDelegate(MultiLineItemDelegate())
		
		self.retranslateUi(None)
		self.setWindowIcon(QIcon(ICON))
		self.show()
		self.resizeTable()
		self.checkUpdates()
		
		# open file
		if load_file:
			_, type = path.splitext(load_file)
			if type.lower() in ['.savj', '.save']: self._openFile(load_file)
			elif type.lower() in ['.binj', '.e']: self._importFile(load_file)
			else: self.showWarning(self.tr('warning.fileNotCompatible') % APPNAME)
	
	def retranslateUi(self, language):
		# change locale
		action2locale = {
			self.actionGerman: 'de',
			self.actionEnglish: 'en',
			self.actionSpanish: 'es',
		}
		if language is None:
			locale = Config.get('language', QLocale.system().name().split('_')[0])
			if not QFile.exists(':/Resources/i18n/%s.qm' % locale): locale = 'en'
			next(k for k, v in action2locale.items() if v == locale).setChecked(True)
		else: locale = action2locale[language]
		Config.set('language', locale)
		translator.load(':/Resources/i18n/%s.qm' % locale)
		app.installTranslator(translator)
		baseTranslator.load(':/Resources/i18n/qtbase_%s.qm' % locale)
		app.installTranslator(baseTranslator)
		
		# update texts
		self.setWindowTitle(APPNAME)
		self.editFilter.setPlaceholderText(self.tr('Filter'))
		self.buttonFilter.setText(self.tr('⨉'))
		self.table.setHorizontalHeaderLabels([self.tr('line'), self.tr('orig.bytes'), self.tr('orig.text'), self.tr('edit.bytes'), self.tr('edit.text')])
		self.menuFile.setTitle(self.tr('File'))
		self.menuHelp.setTitle(self.tr('Help'))
		self.menuEdit.setTitle(self.tr('Edit'))
		self.menuDecodingTable.setTitle(self.tr('Decoding Table'))
		self.actionGoToLine.setText(self.tr('Go to Line...'))
		self.menuView.setTitle(self.tr('View'))
		self.menuTools.setTitle(self.tr('Tools'))
		self.menuSettings.setTitle(self.tr('Settings'))
		self.menuLanguage.setTitle(self.tr('Language'))
		self.actionOpen.setText(self.tr('Open...'))
		self.actionSave.setText(self.tr('Save'))
		self.actionSaveAs.setText(self.tr('Save As...'))
		self.actionImport.setText(self.tr('Import...'))
		self.actionExport.setText(self.tr('Export...'))
		self.actionApplyPatch.setText(self.tr('Apply Patch...'))
		self.actionCreatePatch.setText(self.tr('Create Patch...'))
		self.actionClose.setText(self.tr('Close'))
		self.actionAbout.setText(self.tr('About...') % APPNAME)
		self.actionCheckForUpdates.setText(self.tr('Check for Updates...'))
		self.actionHideEmptyTexts.setText(self.tr('Hide Empty Texts'))
		self.actionScaleRowsToContents.setText(self.tr('Scale Rows to Contents'))
		self.actionDecodingTableFromSav.setText(self.tr('Table from Save'))
		self.actionSeparatorToken.setText(self.tr('Separator Token...'))
		self.actionFTPClient.setText(self.tr('Send via FTP...'))
		self.actionSearchDlg.setText(self.tr('Search in Files...'))
		self.actionNoDecodingTable.setText(self.tr('No Table'))
	
	def keyPressEvent(self, event):
		""" Custom key press event. """
		super(Window, self).keyPressEvent(event)
		self.keysPressed.add(event.key())
		if self.table.currentItem():
			self.tableCellKeyPressed(self.table.currentRow(), self.table.currentColumn(), self.keysPressed)
	
	def keyReleaseEvent(self, event):
		""" Custom key release event. """
		super(Window, self).keyReleaseEvent(event)
		if event.key() in self.keysPressed:
			self.keysPressed.remove(event.key())
	
	def resizeEvent(self, newSize):
		""" Called when the window is resized. """
		self.resizeTable()
	
	def closeEvent(self, event):
		# ask if file was changed
		if self.flag['changed']:
			# ask to save and abort closing if did not save or cancel
			if not self.askSaveWarning(self.tr('warning.saveBeforeClosing')): event.ignore()
		# close all dialogs
		for dlg in self.dialogs:
			dlg.close()
	
	## UPDATES ##
	
	def checkUpdates(self, showFailure = False):
		""" Queries the github api for a new release. """
		try:
			# query api
			latest = r'https://api.github.com/repos/%s/releases/latest' % REPOSITORY
			with urlopen(latest) as url:
				data = json.loads(url.read().decode())
			tag = data['tag_name']
			info = data['body']
			link = data['html_url']
			
			# compare versions
			def ver2int(s):
				if s[0] == 'v': s = s[1:]
				v = s.split('.')
				return sum([int(k) * 100**(len(v)-i) for i, k in enumerate(v)])
			current_version = ver2int(VERSION)
			tag_version = ver2int(tag)
			
			if current_version == tag_version:
				if showFailure: self.showInfo(self.tr('update.newestVersion') % APPNAME)
				return
			
			if current_version > tag_version:
				if showFailure: self.showInfo(self.tr('update.newerVersion') % APPNAME)
				return
			
			# show message
			msg = QMessageBox()
			msg.setWindowTitle(self.tr('Check for Updates...'))
			msg.setWindowIcon(QIcon(ICON))
			text = '<html><body><p>%s</p><p>%s: <code>%s</code><br/>%s: <code>%s</code></p><p>%s</p></body></html>'
			msg.setText(text % (self.tr('update.newVersionAvailable') % APPNAME, self.tr('update.currentVersion'), VERSION, self.tr('update.newVersion'), tag, self.tr('update.doWhat')))
			info = re.sub(r'!\[([^\]]*)\]\([^)]*\)', '', info) # remove images
			info = re.sub(r'\[([^\]]*)\]\([^)]*\)', '\\1', info) # remove links
			info = re.sub(r'__([^_\r\n]*)__|_([^_\r\n]*)_|\*\*([^\*\r\n]*)\*\*|\*([^\*\r\n]*)\*|`([^`\r\n]*)`', '\\1\\2\\3\\4\\5', info) # remove bold, italic and inline code
			msg.setDetailedText(info.strip())
			button_open_website = QPushButton(self.tr('update.openWebsite'))
			msg.addButton(button_open_website, QMessageBox.AcceptRole)
			msg.addButton(QMessageBox.Cancel)
			msg.exec_()
			res = msg.clickedButton()
			
			# open website
			if msg.clickedButton() == button_open_website:
				webbrowser.open(link)
			
		except Exception as e:
			print('Warning: Checking for updates failed:', str(e))
			if showFailure: self.showError(self.tr('update.failed'), str(e))
	
	## FILES ##
	
	def openFile(self):
		""" Opens a .savJ or .savE file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		# ask filename
		dir = Config.get('sav-dir', ROOT)
		if dir and not path.exists(dir): dir = ROOT
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('open'), dir, self.tr('type.savj_save') + ';;' + self.tr('type.savj') + ';;' + self.tr('type.save'))
		if not filename: return False
		Config.set('sav-dir', path.dirname(filename))
		# open file
		return self._openFile(filename)
	
	def _openFile(self, filename):
		""" Implements opening of .savJ and .savE files. """
		self.updateFilename(filename, True)
		_, type = path.splitext(filename)
		
		# load and set extra for savJ, set mode
		if type.lower() == '.savj':
			with ZipFile(filename, 'r') as zip:
				prefix = zip.read('prefix.bin')
			self.extra = {'prefix': prefix}
			self.info['mode'] = 'binJ'
		
		# load and set extra for savE, set mode
		elif type.lower() == '.save':
			with ZipFile(filename, 'r') as zip:
				prefix = zip.read('prefix.bin')
				header = zip.read('header.datE').decode('ASCII')
				scripts = zip.read('scripts.spt').decode('ASCII')
				links = zip.read('links.tabE').decode('ASCII')
			header = parseDatE(header)
			scripts = parseSpt(scripts)
			links = parseTabE(links)
			self.extra = {'prefix': prefix, 'header': header, 'scripts': scripts, 'links': links}
			self.info['mode'] = 'e'
		
		# load data for both
		with ZipFile(filename, 'r') as zip:
			origj = zip.read('orig.datJ').decode('ASCII')
			editj = zip.read('edit.datJ').decode('ASCII')
			SEP = zip.read('SEP.bin')
			specialj = zip.read('special.tabJ').decode('UTF-8')
			decodej = zip.read('decode.tabJ').decode('ASCII')
			encodej = zip.read('encode.tabJ').decode('ASCII')
		orig_data = parseDatJ(origj)
		edit_data = parseDatJ(editj)
		special = parseTabJ(specialj, hexValue = False)
		decode = parseTabJ(decodej, hexValue = True)
		encode = parseTabJ(encodej, hexValue = True)
		decode = {**decode, **invertDict(encode)} # restore full decode
		decodingTable = {'decode': decode, 'encode': encode, 'special': special}
		
		# set data
		self.flag['editing'] = True
		self.cache['decodingTableFromSave'] = decodingTable
		self.info['SEP'] = SEP
		self.updateDecodingTable(self.actionDecodingTableFromSav)
		self.flag['editing'] = False
		self.setData(orig_data, edit_data)
		return True
	
	def saveFile(self):
		""" Saves the current .savJ or .savE file. """
		return self._saveFile(self.info['filename'])
	
	def saveFileAs(self):
		""" Saves a .savJ or .savE file. """
		# ask filename
		dir = Config.get('sav-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.join(ROOT, path.splitext(self.info['filename'])[0])
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('saveAs'), dir, {'binJ': self.tr('type.savj'), 'e': self.tr('type.save')}[self.info['mode']])
		if not filename: return False
		Config.set('sav-dir', path.dirname(filename))
		# save savJ or savE
		return self._saveFile(filename)
	
	def _saveFile(self, filename):
		""" Implements saving of .savJ and .savE files.
			Writes the original text to 'orig.datJ'.
			Writes the edited text to 'edit.datJ'.
			Writes the SEP char to 'SEP.bin'.
			Writes the special chars to 'special.tabJ'.
			Writes the reduced decoding table to 'decode.tabJ'.
			Writes the encoding table to 'encode.tabJ'.
			Stores these files an the given file as a zip archive.
			
			For .savJ files:
			  Writes the prefix to 'prefix.bin'.
			
			For .savE files:
			  Writes the prefix to 'prefix.bin'.
			  Writes the header to 'header.datE'.
			  Writes the scripts to 'scripts.spt'.
			  Writes the links to 'links.tabE'.
		"""
		self.info['filename'] = filename
		self.updateFilename(filename, True)
		
		# create data objects
		origj = createDatJ([bytes for bytes, _, _, _ in self.data])
		editj = createDatJ([bytes for _, _, bytes, _ in self.data])
		specialj = createTabJ(self.info['decodingTable']['special'], hexValue = False)
		decode = self.info['decodingTable']['decode']
		encode = self.info['decodingTable']['encode']
		decode = {k: decode[k] for k in set(decode) - set(invertDict(encode))} # remove every char that is in encode as well
		decodej = createTabJ(decode, hexValue = True)
		encodej = createTabJ(encode, hexValue = True)
		
		# save temporary files
		orig_filename = path.join(tempdir(), 'orig.datJ')
		with open(orig_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(origj)
		edit_filename = path.join(tempdir(), 'edit.datJ')
		with open(edit_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(editj)
		sep_filename = path.join(tempdir(), 'SEP.bin')
		with open(sep_filename, 'wb') as file:
			file.write(self.info['SEP'])
		special_filename = path.join(tempdir(), 'special.tabJ')
		with open(special_filename, 'w', encoding = 'UTF-8', newline = '\n') as file:
			file.write(specialj)
		decode_filename = path.join(tempdir(), 'decode.tabJ')
		with open(decode_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(decodej)
		encode_filename = path.join(tempdir(), 'encode.tabJ')
		with open(encode_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(encodej)
		
		# create data objects and save temporary files for savJ
		if self.info['mode'] == 'binJ':
			prefix_filename = path.join(tempdir(), 'prefix.bin')
			with open(prefix_filename, 'wb') as file:
				file.write(self.extra['prefix'])
		
		# create data objects and save temporary files for savE
		elif self.info['mode'] == 'e':
			prefix_filename = path.join(tempdir(), 'prefix.bin')
			with open(prefix_filename, 'wb') as file:
				file.write(self.extra['prefix'])
			header = createDatE(self.extra['header'])
			header_filename = path.join(tempdir(), 'header.datE')
			with open(header_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
				file.write(header)
			scripts = createSpt(self.extra['scripts'])
			scripts_filename = path.join(tempdir(), 'scripts.spt')
			with open(scripts_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
				file.write(scripts)
			links = createTabE(self.extra['links'])
			links_filename = path.join(tempdir(), 'links.tabE')
			with open(links_filename, 'w', encoding = 'ASCII', newline = '\n') as file:
				file.write(links)
		
		# save savJ
		if self.info['mode'] == 'binJ':
			with ZipFile(filename, 'w') as file:
				file.write(orig_filename, arcname=path.basename(orig_filename))
				file.write(edit_filename, arcname=path.basename(edit_filename))
				file.write(sep_filename, arcname=path.basename(sep_filename))
				file.write(special_filename, arcname=path.basename(special_filename))
				file.write(decode_filename, arcname=path.basename(decode_filename))
				file.write(encode_filename, arcname=path.basename(encode_filename))
				file.write(prefix_filename, arcname=path.basename(prefix_filename))
		
		# save savE
		elif self.info['mode'] == 'e':
			with ZipFile(filename, 'w') as file:
				file.write(orig_filename, arcname=path.basename(orig_filename))
				file.write(edit_filename, arcname=path.basename(edit_filename))
				file.write(sep_filename, arcname=path.basename(sep_filename))
				file.write(special_filename, arcname=path.basename(special_filename))
				file.write(decode_filename, arcname=path.basename(decode_filename))
				file.write(encode_filename, arcname=path.basename(encode_filename))
				file.write(prefix_filename, arcname=path.basename(prefix_filename))
				file.write(header_filename, arcname=path.basename(header_filename))
				file.write(scripts_filename, arcname=path.basename(scripts_filename))
				file.write(links_filename, arcname=path.basename(links_filename))
		
		# remove temporary files
		os.remove(orig_filename)
		os.remove(edit_filename)
		os.remove(sep_filename)
		os.remove(special_filename)
		os.remove(decode_filename)
		os.remove(encode_filename)
		if self.info['mode'] == 'binJ':
			os.remove(prefix_filename)
		elif self.info['mode'] == 'e':
			os.remove(prefix_filename)
			os.remove(header_filename)
			os.remove(scripts_filename)
			os.remove(links_filename)
		
		# update decoding table
		self.cache['decodingTableFromSave'] = self.info['decodingTable']
		self.updateDecodingTable(self.actionDecodingTableFromSav)
		return True
	
	def closeFile(self):
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		# close file
		self.info['filename'] = None
		self.info['mode'] = None
		self.info['SEP'] = None
		self.data = None
		self.extra = dict()
		self.updateFilename(None)
		self.setData(list())
		return True
	
	def importFile(self):
		""" Imports a .binJ or .e file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		# ask filename
		dir = Config.get('import-file-dir', ROOT)
		if dir and not path.exists(dir): dir = ROOT
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('import'), dir, self.tr('type.binj_e') + ';;' + self.tr('type.binj') + ';;' + self.tr('type.e'))
		if not filename: return False
		Config.set('import-file-dir', path.dirname(filename))
		# import file
		return self._importFile(filename)
	
	def _importFile(self, filename):
		""" Implements importing of .binJ and .e files. """
		self.updateFilename(filename, False)
		_, type = path.splitext(filename)
		
		# load SEP from config
		self.info['SEP'] = parseHex(Config.get('SEP', 'E31B'))
		
		# update decoding table
		self.flag['loading'] = True # update decoding table should not update filename
		if self.actionDecodingTableFromSav.isChecked(): self.updateDecodingTable(None) # select default if from savj was selected
		self.cache['decodingTableFromSave'] = None
		self.flag['loading'] = False
		
		# load and set data, set mode
		try:
			if type.lower() == '.binj':
				with open(filename, 'rb') as file: bin = file.read()
				orig_data, extra = parseBinJ(bin, self.info['SEP'])
				self.info['mode'] = 'binJ'
			elif type.lower() == '.e':
				with GzipFile(filename, 'r') as file: bin = file.read()
				orig_data, extra = parseE(bin, self.info['SEP'])
				self.info['mode'] = 'e'
			self.extra = extra
			self.setData(orig_data)
			return True
		except:
			self.showError(self.tr('error.importFailed'))
			self.info['filename'] = None
			self.info['mode'] = None
			self.info['SEP'] = None
			self.data = None
			self.extra = dict()
			self.updateFilename(None)
			self.setData(list())
			return False
	
	def exportFile(self):
		""" Exports a .binJ or .e file. """
		dir = Config.get('export-file-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.join(ROOT, path.splitext(self.info['filename'])[0])
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.binj'), 'e': self.tr('type.e')}[self.info['mode']])
		if not filename: return False
		Config.set('export-file-dir', path.dirname(filename))
		return self._exportFile(filename)
	
	def _exportFile(self, filename):
		""" Implements exporting of .binJ and .e files. """
		# create data
		data = [edit if edit else orig for orig, _, edit, _ in self.data]
		
		# save data
		if self.info['mode'] == 'binJ':
			bin = createBinJ(data, self.info['SEP'], self.extra)
			with open(filename, 'wb') as file: file.write(bin)
		elif self.info['mode'] == 'e':
			bin = createE(data, self.info['SEP'], self.extra)
			with open(filename, 'wb') as file:
				with GzipFile(fileobj=file, mode='w', filename='', mtime=0) as gzipFile: gzipFile.write(bin)
		return True
	
	def importPatch(self):
		""" Imports a patch from a .patJ / .patE or compatible .binJ / .e file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		# ask filename
		dir = Config.get('import-patch-dir', ROOT)
		if dir and not path.exists(dir): dir = ROOT
		extensions = {
			'binJ': self.tr('type.patj_binj') + ';;' + self.tr('type.patj') + ';;' + self.tr('type.binj'),
			'e':    self.tr('type.pate_e')    + ';;' + self.tr('type.pate') + ';;' + self.tr('type.e')
		}[self.info['mode']]
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('import'), dir, extensions)
		if not filename: return False
		Config.set('import-patch-dir', path.dirname(filename))
		# import patch
		return self._importPatch(filename)
	
	def _importPatch(self, filename):
		""" Implements importing of .patJ / .patE and .binJ / .e files. """
		_, type = path.splitext(filename)
		
		# import from patj / pate
		if type.lower() in ['.patj', '.pate']:
			with open(filename, 'r', encoding = 'ASCII') as file:
				patch = file.read()
			edit_data = parseDatJ(patch)
			
			# check if compatible
			if len(edit_data) != len(self.data):
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return False
				# trim or pad edit data
				if len(edit_data) > len(self.data): edit_data = edit_data[:len(self.data)]
				else: edit_data = edit_data + [b'']*(len(self.data) - len(edit_data))
			
			# set data
			orig_data = [bytes for bytes, _, _, _ in self.data]
			self.updateFilename() # show file changed
			self.setData(orig_data, edit_data)
		
		# import from binj / e file
		elif type.lower() in ['.binj', '.e']:
			# check separator
			if self.info['SEP'] != parseHex(Config.get('SEP', 'E31B')):
				# different tokens -> ask which one to use
				sep_from_settings = Config.get('SEP', 'E31B')
				sep_from_current_file = createHex(self.info['SEP']).replace(' ', '')
				msg = QMessageBox()
				msg.setIcon(QMessageBox.Critical)
				msg.setWindowTitle(self.tr('warning'))
				msg.setWindowIcon(QIcon(ICON))
				msg.setText(self.tr('warning.differentSeparatorTokens') % (sep_from_settings, sep_from_current_file))
				button_from_settings = QPushButton(sep_from_settings)
				button_from_current_file = QPushButton(sep_from_current_file)
				msg.addButton(button_from_settings, QMessageBox.AcceptRole)
				msg.addButton(button_from_current_file, QMessageBox.AcceptRole)
				msg.addButton(QMessageBox.Cancel)
				msg.exec_()
				res = msg.clickedButton()
				if msg.clickedButton() == button_from_settings:
					SEP = parseHex(sep_from_settings)
				elif msg.clickedButton() == button_from_current_file:
					SEP = self.info['SEP']
				else: return False # abort
			else: SEP = self.info['SEP']
			
			try:
				if type.lower() == '.binj':
					with open(filename, 'rb') as file: edit_bin = file.read()
					edit_data, extra = parseBinJ(edit_bin, SEP)
				elif type.lower() == '.e':
					with GzipFile(filename, 'r') as file: edit_bin = file.read()
					edit_data, extra = parseE(edit_bin, SEP)
			except:
				self.showError(self.tr('error.importFailed'))
				return False
			
			# check if compatible
			if len(edit_data) != len(self.data): # check data length
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return False
				# trim or pad edit data
				if len(edit_data) > len(self.data): edit_data = edit_data[:len(self.data)]
				else: edit_data = edit_data + [b'']*(len(self.data) - len(edit_data))
			
			# check if compatible for binj
			if self.info['mode'] == 'binJ':
				if extra['prefix'] != self.extra['prefix']:
					# prefixes do not match -> show warning and ask to continue
					if not self.askWarning(self.tr('warning.prefixesDiffer')): return False
			
			# check if compatible for binj
			elif self.info['mode'] == 'e':
				# something does not match -> show warning and ask to continue
				if extra['prefix'] != self.extra['prefix']:
					if not self.askWarning(self.tr('warning.prefixesDiffer')): return False
				if extra['header'] != self.extra['header']:
					if not self.askWarning(self.tr('warning.HeadersDiffer')): return False
				if extra['scripts'] != self.extra['scripts']:
					if not self.askWarning(self.tr('warning.ScriptsDiffer')): return False
				if extra['links'] != self.extra['links']:
					if not self.askWarning(self.tr('warning.LinksDiffer')): return False
			
			# set data
			orig_data = [bytes for bytes, _, _, _ in self.data]
			edit_data = [edit if edit != orig else b'' for orig, edit in zip(orig_data, edit_data)] # filter equal elements
			self.updateFilename() # show file changed
			self.setData(orig_data, edit_data)
			return True
	
	def exportPatch(self):
		""" Exports a patch file as a .patJ or .patE file. """
		dir = Config.get('export-patch-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.join(ROOT, path.splitext(self.info['filename'])[0])
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.patj'), 'e': self.tr('type.pate')}[self.info['mode']])
		if not filename: return False
		_, type = path.splitext(filename)
		Config.set('export-patch-dir', path.dirname(filename))
		return self._exportPatch(filename)
	
	def _exportPatch(self, filename):
		""" Implements exporting of .patJ and .patE files. """
		# create patch
		patch = createDatJ([bytes for _, _, bytes, _ in self.data])
		
		# save patJ or patE
		with open(filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(patch)
		return True
	
	## DIALOGS ##
	
	def showAbout(self):
		""" Displays the about window. """
		msg = QMessageBox()
		msg.setIconPixmap(ICON.scaledToWidth(112))
		msg.setWindowTitle(self.tr('about.title'))
		msg.setWindowIcon(QIcon(ICON))
		text = '''<html><body style="text-align: center; font-size: 10pt">
					<p><b style="font-size: 14pt">%s </b><b>%s</b>
					<br/>@ <a href="%s">%s</a></p>
					<p style="text-align: center;">%s</p>
					<p>%s</p>
				</body></html>'''
		msg.setText(text % (APPNAME, VERSION, 'https://github.com/%s' % REPOSITORY, 'GitHub', AUTHOR, self.tr('about.specialThanks') % SPECIAL_THANKS))
		msg.setStandardButtons(QMessageBox.Ok)
		msg.exec_()
	
	def editSeparatorToken(self):
		dlg = QInputDialog()
		dlg.setWindowFlags(Qt.WindowCloseButtonHint)
		dlg.setWindowTitle(self.tr('settings'))
		dlg.setWindowIcon(QIcon(ICON))
		dlg.setLabelText(self.tr('dlg.editSeparatorToken'))
		dlg.setTextValue(Config.get('SEP', 'E31B'))
		if not dlg.exec_(): return
		new_sep = dlg.textValue()
		if len(new_sep) % 2 != 0 or any(c not in '0123456789ABCDEFabcdef' for c in new_sep):
			self.showError(self.tr('error.editSeparatorTokenFailed'))
			self.editSeparatorToken()
			return
		Config.set('SEP', new_sep.upper())
	
	def goToLine(self):
		dlg = QInputDialog()
		dlg.setInputMode(QInputDialog.IntInput)
		dlg.setIntMinimum(1)
		dlg.setIntMaximum(self.table.rowCount())
		dlg.setWindowFlags(Qt.WindowCloseButtonHint)
		dlg.setWindowTitle(self.tr('Go to Line...'))
		dlg.setWindowIcon(QIcon(ICON))
		dlg.setLabelText(self.tr('dlg.goToLine'))
		current_row = self.table.currentRow()
		line = self.table.item(current_row, 0).data() if current_row != -1 else 1
		dlg.setIntValue(line)
		if not dlg.exec_(): return
		new_line = dlg.intValue()
		self.table.clearSelection()
		line2row = {self.table.item(r, 0).data(): r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r) and self.table.item(r, 0).data() >= new_line}
		if line2row:
			new_row = sorted(line2row.items())[0][1]
			self.table.setCurrentCell(new_row, 4)
		self.scrollToSelectedItem()
	
	def showError(self, text, detailedText = None):
		""" Displays an error message. """
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Critical)
		msg.setWindowTitle(self.tr('error'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QMessageBox.Ok)
		msg.exec_()
	
	def showWarning(self, text, detailedText = None):
		""" Displays a warning message. """
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QMessageBox.Ok)
		msg.exec_()
	
	def askWarning(self, text, detailedText = None):
		""" Displays a warning message and asks yes or no.
			Returns True if yes was selected.
		"""
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
		return msg.exec_() == QMessageBox.Yes
	
	def askSaveWarning(self, text):
		""" Displays a warning message and asks yes, no or cancel.
			If yes was chosen, the current file will be saved.
			Returns True if the file was successfully saved or No was chosen.
		"""
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
		res = msg.exec_()
		if res == QMessageBox.Yes:
			# yes -> save or saveAs
			# return True if progress was saved
			if self.flag['savable']:
				self.saveFile()
				return True
			else:
				return self.saveFileAs()
		elif res == QMessageBox.No:
			# no -> return True
			return True
		elif res == QMessageBox.Cancel:
			# cancel -> return False
			return False
	
	def showInfo(self, text, detailedText = None):
		""" Displays a warning message. """
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Information)
		msg.setWindowTitle(self.tr('information'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QMessageBox.Ok)
		msg.exec_()
	
	## PROPERTIES ##
	
	def updateFilename(self, filename = None, savable = None):
		""" Called when a new file is loaded or an edit is made.
			Updates the changed flag and filename info variabe.
			Enables the actionSave option.
			Sets the correct title of the window.
		"""
		# set changed, false if new file is loaded
		self.flag['changed'] = self.info['filename'] is not None and filename is None
		# store current filename and savable
		if filename is not None: self.info['filename'] = filename
		if savable is not None: self.flag['savable'] = savable
		# activate/deactivate save action and from savj
		self.actionSave.setEnabled(self.flag['savable'])
		self.actionDecodingTableFromSav.setEnabled(self.flag['savable'])
		# set window title
		if self.info['filename']:
			self.setWindowTitle('%s%s - %s' % ('*' if self.flag['changed'] else '', path.basename(self.info['filename']), APPNAME))
		else: self.setWindowTitle(APPNAME)
		actions_enabled = self.info['filename'] is not None
		self.actionSaveAs.setEnabled(actions_enabled)
		self.actionClose.setEnabled(actions_enabled)
		self.actionExport.setEnabled(actions_enabled)
		self.actionApplyPatch.setEnabled(actions_enabled)
		self.actionCreatePatch.setEnabled(actions_enabled)
		self.actionGoToLine.setEnabled(actions_enabled)
		self.actionFTPClient.setEnabled(actions_enabled)
	
	def updateDecodingTable(self, arg):
		""" Called when a new decoding table is chosen.
			Updates the decodingTable info variable.
			Updates the self.menuDecodingTableGroup.
			Calls self.setData() if needed.
		"""
		# save table for later
		oldTable = self.info['decodingTable']
		
		# arg is decoding table from save -> select from save
		if arg is self.actionDecodingTableFromSav:
			self.menuDecodingTableGroup.actions()[0].setChecked(True)
			self.info['decodingTable'] = self.cache['decodingTableFromSave']
		
		# arg is no decoding table -> select none
		elif arg is self.actionNoDecodingTable:
			self.menuDecodingTableGroup.actions()[1].setChecked(True)
			self.info['decodingTable'] = {'encode': dict(), 'decode': dict(), 'special': dict()}
		
		# arg is None -> select default
		elif arg is None:
			# select from config if found
			default = Config.get('decoding-table')
			if default: idx = next((i for i, a in enumerate(self.menuDecodingTableGroup.actions()) if a.data() == default), -1)
			else: idx = -1
			# else use first res or no table
			if idx == -1: idx = 2 if len(self.menuDecodingTableGroup.actions()) >= 3 else 1
			action = self.menuDecodingTableGroup.actions()[idx]
			action.setChecked(True)
			if action is self.actionNoDecodingTable:
				self.info['decodingTable'] = {'encode': dict(), 'decode': dict(), 'special': dict()}
			else: self.info['decodingTable'] = parseDecodingTable(action.data())
		
		# arg is normal option -> select option by given filename
		else:
			filename = arg.data()
			Config.set('decoding-table', filename)
			action = next(action for action in self.menuDecodingTableGroup.actions() if action.data() == filename)
			action.setChecked(True)
			self.info['decodingTable'] = parseDecodingTable(filename)
		
		# check whether data changed
		if self.info['decodingTable'] != oldTable:
			# not loading -> show file changed
			if not self.flag['loading'] and not self.flag['editing']:
				self.updateFilename()
			# file loaded -> update data
			if self.data:
				orig_data = [bytes for bytes, _, _, _ in self.data]
				edit_data = [bytes for _, _, bytes, _ in self.data]
				self.setData(orig_data, edit_data)
	
	def resizeTable(self):
		""" Resizes the table.
			The columns are distributed equally.
		"""
		# resize columns
		number_width = 40
		scrollbar_width = 20
		self.table.setColumnWidth(0, number_width)
		visible_columns = sum(1 for column in range(1, 5) if not self.table.isColumnHidden(column))
		column_width = int((self.table.width() - self.table.verticalHeader().width() - number_width - scrollbar_width) / visible_columns)
		for column in range(1, 5):
			if self.table.isColumnHidden(column): continue
			self.table.setColumnWidth(column, column_width)
		
		# update automatic linebreaks
		scaleRows = self.actionScaleRowsToContents.isChecked()
		for r in range(self.table.rowCount()):
			for c in [2, 4]:
				self.table.item(r, c).setAutomaticLinebreaksEnabled(scaleRows)
		
		# resize rows
		if scaleRows:
			self.table.resizeRowsToContents()
		else:
			self.table.verticalHeader().setDefaultSectionSize(self.table.verticalHeader().defaultSectionSize())
		
		# scroll to selection
		self.scrollToSelectedItem()
	
	## DATA ##
	
	def setData(self, orig_data, edit_data = None):
		""" Sets the data from the given prefix, original bytes and edited bytes.
			Updates the data.
			Resizes the table by calling self.resizeTable().
		"""
		# clear table and data, start loading
		self.flag['loading'] = True
		self.table.setSortingEnabled(False)
		self.editFilter.clear()
		self.table.setRowCount(0)
		oldLength = len(self.data) if self.data else 0
		self.data = list()
		scaleRows = self.actionScaleRowsToContents.isChecked()
		
		# add to data and table
		for i, orig_key in enumerate(orig_data):
			orig_value = bytes2list(orig_key, self.info['decodingTable'], self.info['SEP'])
			# get edit data
			if edit_data and edit_data[i]:
				edit_key = edit_data[i]
				edit_value = bytes2list(edit_key, self.info['decodingTable'], self.info['SEP'])
			else: edit_key, edit_value = (b'', list())
			# add to data
			self.data.append((orig_key, orig_value, edit_key, edit_value))
			# add row
			row = self.table.rowCount()
			self.table.insertRow(row)
			# line
			item = IntTableWidgetItem(i+1)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 0, item)
			# original bytes
			item = HexBytesTableWidgetItem(orig_key)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 1, item)
			# original text
			item = ListTableWidgetItem(orig_value, scaleRows)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 2, item)
			# edit bytes
			item = HexBytesTableWidgetItem(edit_key)
			self.table.setItem(row, 3, item)
			# edit text
			item = ListTableWidgetItem(edit_value, scaleRows)
			self.table.setItem(row, 4, item)
		
		# resize table, finish loading
		self.resizeTable()
		if len(self.data) != oldLength: # scroll to top if data changed
			self.table.verticalScrollBar().setValue(0)
		QTimer.singleShot(20, self.resizeTable) # wait for scrollbar
		self.editFilter.setText('')
		self.table.setSortingEnabled(True)
		self.filterData()
		self.flag['loading'] = False
	
	def filterData(self):
		""" Filters the data. Does not search the index. """
		filter = self.editFilter.text()
		hideEmpty = self.actionHideEmptyTexts.isChecked()
		
		for row in range(self.table.rowCount()):
			visible = True
			if hideEmpty and not self.table.item(row, 1).text() and not self.table.item(row, 3).text(): visible = False
			if filter and not any(filter.lower() in self.table.item(row, column).text().lower() for column in range(1, 5)): visible = False
			if visible: self.table.showRow(row)
			else: self.table.hideRow(row)
		
		QTimer.singleShot(10, self.scrollToSelectedItem) # wait for scrollbar
	
	def scrollToSelectedItem(self):
		if not self.table.selectedItems(): return
		item = self.table.selectedItems()[0]
		self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
	
	def tableCellChanged(self, row, column):
		""" Called when a cell was changed.
			Updates the data.
		"""
		if self.flag['loading'] or self.flag['editing']: return
		
		# get cells
		bytes_cell = self.table.item(row, 3)
		list_cell  = self.table.item(row, 4)
		id = self.table.item(row, 0).data() - 1 # logical row
		
		# edit bytes
		if column == 3:
			bytes = bytes_cell.data()
			lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # convert to list
		
		# edit text
		if column == 4:
			lst = list_cell.data()
			# convert to bytes
			try:
				bytes = list2bytes(lst, self.info['decodingTable'], self.info['SEP'])
				lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # de-escape chars
			except Exception as e:
				self.showError(self.tr('error.unknownChar') % e.args[0])
				self.flag['editing'] = True
				list_cell.setData(data=self.data[id][3])
				self.flag['editing'] = False
				return
		
		# change data and cells
		self.flag['editing'] = True
		self.updateFilename()
		bytes_cell.setData(data=bytes)
		list_cell.setData(data=lst)
		self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
		if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowToContents(row)
		self.flag['editing'] = False
	
	def tableCellKeyPressed(self, row, column, keys):
		""" Called when a key is pressed while focussing a table cell. """
		# Ctrl+C -> copy
		if {Qt.Key_Control, Qt.Key_C} == keys:
			indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
			
			# create copy string
			s, lr = ('', None)
			for r, c in sorted(indices):
				text = self.table.item(r, c).text()
				text = text.replace('\n', '')
				if lr is not None: s += '\t' if r == lr else linesep # go to next row or column
				s += text
				lr = r
			
			# copy to clipboard
			clipboard.copy(s)
			return
		
		# Ctrl+V -> paste
		if {Qt.Key_Control, Qt.Key_V} == keys:
			# get clipboard content
			content = clipboard.paste() # get clipboard content
			content = content.splitlines() # split content into lines
			
			# collect indices for pasting
			indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
			indices = [(r, c) for r, c in indices if c in [3, 4]] # filter selection for editable columns
			if not indices: return
			if len(set(c for _, c in indices)) > 1: # filter if multiple columns selected
				indices = [(r, c) for r, c in indices if c == 4] # prefer copy to text
				content = [x.split('\t')[1] if '\t' in x else x for x in content] # use second column only
			elif '\t' in content[0]: # filter if single column selected but content has many columns
				index = 0 if indices[0][1] == 3 else 1
				content = [x.split('\t')[index] for x in content] # use corresponding column only
			
			# paste
			self.table.setSortingEnabled(False)
			for i, (r, c) in enumerate(indices):
				if len(content) == 1: text = content[0] # always use single line
				elif i < len(content): text = content[i] # use next line
				else: break # stop pasting
				
				bytes_cell = self.table.item(r, 3)
				list_cell  = self.table.item(r, 4)
				id = self.table.item(r, 0).data() - 1 # logical row
				
				# paste to bytes
				if c == 3:
					bytes = parseHex(text)
					lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # convert to list
				
				# paste to text
				elif c == 4:
					lst = text2list(text)
					# convert to bytes
					try:
						bytes = list2bytes(lst, self.info['decodingTable'], self.info['SEP'])
						lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # de-escape chars
					except Exception as e:
						self.showError(self.tr('error.unknownChar') % e.args[0])
						self.keysPressed.clear() # prevent keys from keeping pressed
						self.flag['editing'] = True
						list_cell.setData(data=self.data[id][3])
						self.flag['editing'] = False
						break # break loop
				
				# change data and cells
				self.flag['editing'] = True
				self.updateFilename()
				bytes_cell.setData(data=bytes)
				list_cell.setData(data=lst)
				self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
				if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowToContents(r)
				self.flag['editing'] = False
			self.table.setSortingEnabled(True)
			return
		
		# Ctrl+X -> cut
		if {Qt.Key_Control, Qt.Key_X} == keys:
			# collect indices for pasting
			indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
			indices = [(r, c) for r, c in indices if c in [3, 4]] # filter selection for editable columns
			columns = sorted({c for _, c in indices}) # collect columns
			rows = sorted({r for r, _ in indices}) # collect rows
			if not rows: return
			
			# create copy string and clear data
			s = ''
			self.table.setSortingEnabled(False)
			for r in rows:
				# copy
				if s != '': s += linesep # go to next row
				for j, c in enumerate(columns):
					text = self.table.item(r, c).text()
					text = text.replace('\n', '')
					if j: s += '\t' # go to next column
					s += text
				
				# clear
				id = self.table.item(r, 0).data() - 1 # logical row
				self.flag['editing'] = True
				self.updateFilename()
				self.table.item(r, 3).setData(data=b'')
				self.table.item(r, 4).setData(data=list())
				self.data[id] = (self.data[id][0], self.data[id][1], b'', list())
				if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowToContents(r)
				self.flag['editing'] = False
			self.table.setSortingEnabled(True)
			
			# copy to clipboard
			clipboard.copy(s)
			return
		
		# Del -> clear
		if Qt.Key_Delete in keys:
			# collect indices for pasting
			indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
			indices = [(r, c) for r, c in indices if c in [3, 4]] # filter selection for editable columns
			rows = {r for r, _ in indices} # collect rows
			
			self.table.setSortingEnabled(False)
			for r in sorted(rows):
				id = self.table.item(r, 0).data() - 1 # logical row
				self.flag['editing'] = True
				self.updateFilename()
				self.table.item(r, 3).setData(data=b'')
				self.table.item(r, 4).setData(data=list())
				self.data[id] = (self.data[id][0], self.data[id][1], b'', list())
				if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowToContents(r)
				self.flag['editing'] = False
			self.table.setSortingEnabled(True)
			return
		
		# Return/Enter -> next cell
		if Qt.Key_Return in keys or Qt.Key_Enter in keys:
			if Qt.Key_Shift in keys: # + Shift -> next empty cell
				next_row = next((r for r in range(row + 1, self.table.rowCount()) if not self.table.isRowHidden(r) and not self.table.item(r, 4).text()), row)
			else: next_row = next((r for r in range(row + 1, self.table.rowCount()) if not self.table.isRowHidden(r)), row)
			self.table.setCurrentCell(next_row, column)
			return
	
	def tableCellDoubleClicked(self, row, column):
		if column not in [1, 2]: return
		# copy bytes if edited data is empty
		id = self.table.item(row, 0).data() - 1 # logical row
		if self.data[id][2]: return
		if column == 1:
			bytes = self.data[id][0]
			lst = self.data[id][1]
		elif column == 2:
			lst = self.data[id][1]
			# convert to bytes
			try:
				bytes = list2bytes(lst, self.info['decodingTable'], self.info['SEP'])
				lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # de-escape chars
			except Exception as e:
				self.showError(self.tr('error.unknownChar') % e.args[0])
				self.keysPressed.clear() # prevent keys from keeping pressed
				return # abort
		self.flag['editing'] = True
		self.updateFilename()
		self.table.item(row, 3).setData(data=bytes)
		self.table.item(row, 4).setData(data=lst)
		self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
		if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowToContents(row)
		self.flag['editing'] = False
	
	## MISC ##
	
	def showFTPClient(self):
		# create temporary binj or e file
		data = [edit if edit else orig for orig, _, edit, _ in self.data]
		if self.info['mode'] == 'binJ':
			bin = createBinJ(data, self.info['SEP'], self.extra)
			filename = path.join(tempdir(), path.splitext(path.basename(self.info['filename']))[0] + '.binJ')
			with open(filename, 'wb') as file: file.write(bin)
		elif self.info['mode'] == 'e':
			bin = createE(data, self.info['SEP'], self.extra)
			filename = path.join(tempdir(), path.splitext(path.basename(self.info['filename']))[0] + '.e')
			with open(filename, 'wb') as file:
				with GzipFile(fileobj=file, mode='w', filename='', mtime=0) as gzipFile: gzipFile.write(bin)
		
		# open ftp client and pass the temporary filename
		dlg = FTPClient(filename)
		self.dialogs.append(dlg)
		dlg.exec_()
		
		# delete temporary binj file
		os.remove(filename)
		self.dialogs.remove(dlg)
	
	def showSearchDlg(self):
		dlg = SearchDlg(self.info['SEP'])
		self.dialogs.append(dlg)
		dlg.exec_()
		self.dialogs.remove(dlg)


################
## FTP Client ##
################

class FTPClient(QDialog):
	""" The dialog for sending files using FTP. """
	
	def __init__(self, filename):
		""" filename - the full filename of the file to send
			           AND the filename guess for the destination file
		"""
		super(FTPClient, self).__init__()
		uiFile = QFile(':/Resources/Forms/ftpclient.ui')
		uiFile.open(QFile.ReadOnly)
		loadUi(uiFile, self)
		uiFile.close()
		
		self.src_filename = filename
		name, type = path.splitext(filename)
		if type.lower() == '.binj': mode = 'Message/binJ'
		elif type.lower() == '.e' and path.basename(name).startswith('demo'): mode = 'Demo/e'
		elif type.lower() == '.e': mode = 'Field/e'
		else: mode = 'Default'
		
		self.setWindowFlags(Qt.WindowCloseButtonHint)
		self.setFixedSize(480, 340)
		
		# connection settings
		self.editIP.setText(Config.get('ftp.ip') or '192.168.1.1')
		self.editIP.textChanged.connect(lambda value: Config.set('ftp.ip', value))
		self.editPort.setValidator(QIntValidator(0, 9999))
		self.editPort.setText(str(Config.get('ftp.port', 5000)))
		self.editPort.textChanged.connect(lambda value: Config.set('ftp.port', int(value) if value.isdigit() else None))
		self.editUser.setText(Config.get('ftp.user', ''))
		self.editUser.textChanged.connect(lambda value: Config.set('ftp.user', value))
		self.editPassword.setText(Config.get('ftp.password', ''))
		self.editPassword.textChanged.connect(lambda value: Config.set('ftp.password', value))
		
		# game settings
		ftp_directory_key = {'Default': 'ftp.directory', 'Message/binJ': 'ftp.directory.message', 'Demo/e': 'ftp.directory.demo', 'Field/e': 'ftp.directory.field'}[mode]
		ftp_directory_default_value = {'Default': '/data', 'Message/binJ': '/data/Message', 'Demo/e': '/data/Event/Demo', 'Field/e': '/data/Event/Field'}[mode]
		filename_extension = {'Default': '.binJ', 'Message/binJ': '.binJ', 'Demo/e': '.e', 'Field/e': '.e'}[mode]
		self.editTitleID.setValidator(QRegExpValidator(QRegExp('[0-9a-fA-F]{16}')))
		self.editTitleID.setText(Config.get('ftp.titleid') or '0000000000000000')
		self.editTitleID.textChanged.connect(lambda value: Config.set('ftp.titleid', value.lower()))
		self.editDirectory.setText(Config.get(ftp_directory_key, ftp_directory_default_value))
		self.editDirectory.textChanged.connect(lambda value: Config.set(ftp_directory_key, value))
		self.editFilename.setText(path.splitext(path.basename(filename))[0] + filename_extension)
		
		# remaining ui
		self.buttonSend.clicked.connect(self.send)
		
		# full path actions
		self.editTitleID.textChanged.connect(self.updateFullPath)
		self.editDirectory.textChanged.connect(self.updateFullPath)
		self.editFilename.textChanged.connect(self.updateFullPath)
		self.updateFullPath()
		
		self.retranslateUi()
		self.setWindowIcon(QIcon(ICON))
		self.show()
	
	def retranslateUi(self):
		self.setWindowTitle(self.tr('Send via FTP...'))
		self.labelConnection.setText(self.tr('Connection Settings'))
		self.labelIP.setText(self.tr('3DS IP:'))
		self.labelPort.setText(self.tr('Port:'))
		self.labelUser.setText(self.tr('User:'))
		self.labelPassword.setText(self.tr('Password:'))
		self.labelGame.setText(self.tr('Game Settings'))
		self.labelTitleID.setText(self.tr('Title ID:'))
		self.labelDirectory.setText(self.tr('Directory:'))
		self.labelFilename.setText(self.tr('Filename:'))
		self.buttonSend.setText(self.tr('Send'))
	
	def updateFullPath(self):
		titleid = self.editTitleID.text().lower()
		directory = path.normpath(self.editDirectory.text())
		while directory and directory[0] in ['\\', '/']:
			directory = directory[1:]
		filename = self.editFilename.text()
		fullpath = path.join('luma', 'titles', titleid, 'romfs', directory, filename)
		fullpath = '/' + path.normpath(fullpath).replace('\\', '/')
		self.editFullPath.setText(fullpath)
		self.editFullPath.setCursorPosition(0)
		return fullpath
	
	def send(self):
		# disable all edits
		def setAllElementsEnabled(enabled):
			self.editIP.setEnabled(enabled)
			self.editPort.setEnabled(enabled)
			self.editUser.setEnabled(enabled)
			self.editPassword.setEnabled(enabled)
			self.editTitleID.setEnabled(enabled)
			self.editDirectory.setEnabled(enabled)
			self.editFilename.setEnabled(enabled)
			self.buttonSend.setEnabled(enabled)
		setAllElementsEnabled(False)
		
		# collect parameters
		ip = self.editIP.text()
		port = int(self.editPort.text())
		user = self.editUser.text()
		passwd = self.editPassword.text()
		directories = [x for x in self.updateFullPath().split('/') if x][:-1]
		src_filename = self.src_filename
		dest_filename = self.editFilename.text()
		
		# clear log
		self.editLog.clear()
		def log(line):
			self.editLog.setMarkdown(self.editLog.toMarkdown() + '  ' + line)
			self.editLog.verticalScrollBar().setValue(self.editLog.verticalScrollBar().maximum())
			QApplication.processEvents()
		def output(s): log('» `%s`' % s)
		
		try:
			with open(src_filename, 'rb') as file:
				with FTP(timeout = 3) as ftp:
					log(self.tr('send.connect') % (ip, port))
					output(ftp.connect(host = ip, port = port))
					if user:
						log(self.tr('send.login') % user)
						output(ftp.login(user = user, passwd = passwd))
					for directory in directories:
						if directory not in [dir for dir, _ in ftp.mlsd()]:
							log(self.tr('send.mkd') % directory)
							ftp.mkd(directory)
						ftp.cwd(directory)
					log(self.tr('send.send') % dest_filename)
					output(ftp.storbinary('STOR %s' % dest_filename, file))
					log(self.tr('send.quit'))
					output(ftp.quit())
					log(self.tr('send.done'))
		except Exception as e:
			log(self.tr('send.error') + ' ```%s```' % str(e))
		
		setAllElementsEnabled(True)


################
## Search Dlg ##
################

class SearchDlg(QDialog):
	""" The dialog for searching texts in files. """
	
	def __init__(self, SEP):
		super(SearchDlg, self).__init__()
		uiFile = QFile(':/Resources/Forms/searchdlg.ui')
		uiFile.open(QFile.ReadOnly)
		loadUi(uiFile, self)
		uiFile.close()
		
		self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
		self.SEP = SEP
		
		# key listener
		self.keysPressed = set()
		
		# search button
		self.searching = False
		self.buttonSearch.clicked.connect(lambda: self.toggleSearch())
		self.toggleSearch(False)
		
		# search settings
		for item in Config.get('search.for.history', list()): self.cbSearchFor.addItem(item)
		self.cbSearchFor.setEditText(Config.get('search.for', ''))
		self.cbSearchFor.editTextChanged.connect(lambda value: Config.set('search.for', value))
		self.useRegex.setChecked(Config.get('search.regex', False))
		self.useRegex.stateChanged.connect(lambda value: Config.set('search.regex', value))
		for item in Config.get('search.directory.history', list()): self.cbDirectory.addItem(item)
		self.cbDirectory.setEditText(Config.get('search.directory', ''))
		self.cbDirectory.editTextChanged.connect(lambda value: Config.set('search.directory', value))
		self.buttonChooseDirectory.clicked.connect(self.askDirectory)
		self.buttonChooseDirectory.setFixedWidth(22)
		# files
		self.updateCBFiles()
		# decoding tables
		for file in [f for f in os.listdir(TABLE_PATH) if path.splitext(f)[1] == '.txt']:
			file = path.join(TABLE_PATH, file)
			self.cbDecodingTable.addItem(path.basename(file), userData = file)
		idx = self.cbDecodingTable.findText(Config.get('search.table', ''))
		self.cbDecodingTable.setCurrentIndex(idx if idx != -1 else 0)
		self.cbDecodingTable.currentTextChanged.connect(lambda value: Config.set('search.table', value))
		
		self.retranslateUi()
		self.setWindowIcon(QIcon(ICON))
		self.show()
		self.resizeTable()
	
	def keyPressEvent(self, event):
		""" Custom key press event. """
		super(SearchDlg, self).keyPressEvent(event)
		self.keysPressed.add(event.key())
		if self.table.currentItem():
			self.tableCellKeyPressed(self.table.currentRow(), self.table.currentColumn(), self.keysPressed)
	
	def keyReleaseEvent(self, event):
		""" Custom key release event. """
		super(SearchDlg, self).keyReleaseEvent(event)
		if event.key() in self.keysPressed:
			self.keysPressed.remove(event.key())
	
	def retranslateUi(self):
		self.setWindowTitle(self.tr('Search in Files...'))
		self.labelSettings.setText(self.tr('Search Settings'))
		self.labelSearchFor.setText(self.tr('Search for:'))
		self.useRegex.setText(self.tr('Regex'))
		self.labelDirectory.setText(self.tr('Directory:'))
		self.labelFiles.setText(self.tr('Files:'))
		self.labelDecodingTable.setText(self.tr('Table:'))
		self.buttonSearch.setText(self.tr('Search'))
		self.table.setHorizontalHeaderLabels([self.tr('file'), self.tr('line'), self.tr('text')])
		self.table.setSortingEnabled(True)
		self.updateCBFiles()
	
	def resizeTable(self):
		self.table.setColumnWidth(0, 180)
		self.table.setColumnWidth(1, 40)
	
	def tableCellKeyPressed(self, row, column, keys):
		""" Called when a key is pressed while focussing a table cell. """
		# Ctrl+C -> copy
		if {Qt.Key_Control, Qt.Key_C} != keys: return
		indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
		
		# create copy string
		s, lr = ('', None)
		for r, c in sorted(indices):
			text = self.table.item(r, c).text()
			text = text.replace('\n', '')
			if lr is not None: s += '\t' if r == lr else linesep # go to next row or column
			s += text
			lr = r
		
		# copy to clipboard
		clipboard.copy(s)
	
	def showError(self, text, detailedText = None):
		""" Displays an error message. """
		msg = QMessageBox()
		msg.setIcon(QMessageBox.Critical)
		msg.setWindowTitle(self.tr('error'))
		msg.setWindowIcon(QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QMessageBox.Ok)
		msg.exec_()
	
	def updateCBFiles(self):
		""" Adds the items for supported file types to the combo box.
			Retranslates the strings if called a second time.
		"""
		if self.cbFiles.count() > 0: # clear if called to translate
			self.cbFiles.currentIndexChanged.disconnect()
			self.cbFiles.clear()
		self.cbFiles.addItem(self.tr('type.binj_e_savj_save_patj_pate'), userData = ('.binJ', '.e', '.savJ', '.savE', '.patJ', '.patE'))
		self.cbFiles.addItem(self.tr('type.binj_e'), userData = ('.binJ', '.e'))
		self.cbFiles.addItem(self.tr('type.binj'), userData = ('.binJ',))
		self.cbFiles.addItem(self.tr('type.e'), userData = ('.e',))
		self.cbFiles.addItem(self.tr('type.savj_save'), userData = ('.savJ', '.savE'))
		self.cbFiles.addItem(self.tr('type.savj'), userData = ('.savJ',))
		self.cbFiles.addItem(self.tr('type.save'), userData = ('.savE',))
		self.cbFiles.addItem(self.tr('type.patj_pate'), userData = ('.patJ', '.patE'))
		self.cbFiles.addItem(self.tr('type.patj'), userData = ('.patJ',))
		self.cbFiles.addItem(self.tr('type.pate'), userData = ('.patE',))
		idx = Config.get('search.files', 0)
		self.cbFiles.setCurrentIndex(idx if idx < self.cbFiles.count() else 0)
		self.cbFiles.currentIndexChanged.connect(lambda value: Config.set('search.files', value))
	
	def askDirectory(self):
		""" Ask to choose a directory and updates cbDirectory. """
		dir = QFileDialog.getExistingDirectory(self, self.tr('chooseDirectory'), self.cbDirectory.currentText())
		if not dir: return
		self.cbDirectory.setEditText(dir)
	
	def toggleSearch(self, flag = None):
		""" Updates the self.searching flag and the enabled states of all elements.
			Starts the search.
		"""
		# set self.searching
		if flag is None: self.searching = not self.searching
		else: self.searching = flag
		# update button text
		self.buttonSearch.setText(self.tr('Search') if not self.searching else self.tr('Cancel'))
		# update enabled
		self.progressBar.setEnabled(self.searching)
		self.cbSearchFor.setEnabled(not self.searching)
		self.useRegex.setEnabled(not self.searching)
		self.cbDirectory.setEnabled(not self.searching)
		self.buttonChooseDirectory.setEnabled(not self.searching)
		self.cbFiles.setEnabled(not self.searching)
		self.cbDecodingTable.setEnabled(not self.searching)
		# start search
		if self.searching: self.startSearch()
	
	def startSearch(self):
		""" Searches the specified files. """
		# parse parameters
		searchString = self.cbSearchFor.currentText()
		useRegex = self.useRegex.isChecked()
		directory = self.cbDirectory.currentText()
		fileTypes = self.cbFiles.currentData()
		decodingTable = self.cbDecodingTable.currentData()
		
		# prepare and check parameters
		self.table.setRowCount(0)
		if not path.isdir(directory):
			self.showError(self.tr('error.notADirectory'))
			self.toggleSearch(False)
			return
		if useRegex:
			try:
				pattern = re.compile(searchString)
			except Exception as e:
				self.showError(self.tr('error.invalidRegex'), str(e))
				self.toggleSearch(False)
				return
		decodingTable = parseDecodingTable(decodingTable)
		
		# update search history
		def updateHistory(comboBox, configKey, limit = 10):
			history = Config.get(configKey, list())
			text = comboBox.currentText()
			if not history or history[0] != text: # add to history
				history = [text] + history
				comboBox.insertItem(0, text)
			history = history[:limit] # limit number of entries
			Config.set(configKey, history)
		updateHistory(self.cbSearchFor, 'search.for.history')
		updateHistory(self.cbDirectory, 'search.directory.history')
		
		# collect all files, idle animation
		self.progressBar.setMaximum(0)
		QApplication.processEvents()
		filenames = list()
		for dp, _, fn in os.walk(directory):
			filenames += [path.join(dp, f) for f in fn if path.splitext(f)[1] in fileTypes]
			QApplication.processEvents()
		if len(filenames) == 0: # end if no files found
			self.progressBar.setMaximum(1)
			self.progressBar.setValue(1)
			self.toggleSearch(False)
			return
		self.progressBar.setMaximum(len(filenames))
		self.progressBar.setValue(0)
		
		# search files
		for ctr, filename in enumerate(filenames):
			if not self.searching: return
			
			# extract data
			type = path.splitext(filename)[1]
			if type == '.binJ':
				with open(filename, 'rb') as file: bin = file.read()
				data, _ = parseBinJ(bin, self.SEP)
				data = [data]
			elif type == '.e':
				with GzipFile(filename, 'r') as file: bin = file.read()
				data, _ = parseE(bin, self.SEP)
				data = [data]
			elif type in ['.savJ', '.savE']:
				with ZipFile(filename, 'r') as zip:
					origj = zip.read('orig.datJ').decode('ASCII')
					editj = zip.read('edit.datJ').decode('ASCII')
				orig_data = parseDatJ(origj)
				edit_data = parseDatJ(editj)
				data = [orig_data, edit_data]
			elif type in ['.patJ', '.patE']:
				with open(filename, 'r', encoding = 'ASCII') as file: patch = file.read()
				data = parseDatJ(patch)
				data = [data]
			else: continue
			
			# iterate over multiple data lists if necessary
			for lines in data:
				
				# convert bytes to text
				texts = list()
				for line in lines:
					texts.append(list2text(bytes2list(line, decodingTable, self.SEP)))
					QApplication.processEvents()
				
				# search texts
				for i, line in enumerate(texts):
					if useRegex:
						if not pattern.search(line): continue
					else:
						if searchString.lower() not in line.lower(): continue
					
					# add row
					row = self.table.rowCount()
					self.table.insertRow(row)
					# file
					common_prefix = path.commonprefix((filename, directory))
					file = path.relpath(filename, common_prefix)
					item = QTableWidgetItem(file)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 0, item)
					# line
					item = IntTableWidgetItem(i+1)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 1, item)
					# text
					item = QTableWidgetItem(line)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 2, item)
			
			# update progress bar
			self.progressBar.setValue(ctr+1)
			QApplication.processEvents()
		
		# complete search
		self.toggleSearch(False)


##########
## Main ##
##########

if __name__ == '__main__':
	app = QApplication(list())
	translator = QTranslator()
	baseTranslator = QTranslator()
	ICON = QPixmap(':/Resources/Images/icon.ico')
	filename = sys.argv[1] if len(sys.argv) > 1 else None
	window = Window(filename)
	window.resizeTable()
	app.exec_()
