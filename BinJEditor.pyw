""" Author: Dominik Beese
>>> BinJ Editor
	An editor for .binJ files with custom decoding tables.
<<<
"""

# pip install pyqt5
# pip install pyperclip
from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QInputDialog, QDialog, QMessageBox, QAbstractItemView, QTableWidgetItem, QPushButton, QActionGroup
from PyQt5.QtCore import QTranslator, QLocale, QRegExp, QTimer, QFile, Qt
from PyQt5.QtGui import QRegExpValidator, QIntValidator, QPixmap, QIcon, QFont
from JTools import *
import Resources
import pyperclip as clipboard
import json
import re
import sys
import os
from os import path, linesep
from zipfile import ZipFile
from gzip import GzipFile
from tempfile import gettempdir as tempdir
from ftplib import FTP
import webbrowser
from urllib.request import urlopen

TABLE_PATH = 'Table/'
CONFIG_FILE = 'config.json'

VERSION = 'v1.1.0'
REPOSITORY = r'Ich73/BinJEditor'
AUTHOR = 'Dominik Beese 2020'
SPECIAL_THANKS = 'Frank Colmines'


###########
## Setup ##
###########

# set windows taskbar icon
try:
	from PyQt5.QtWinExtras import QtWin
	appid = 'binjeditor.' + VERSION
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
		with open(CONFIG_FILE, 'r') as file:
			Config.cfg = json.load(file)
	
	def saveConfig():
		with open(CONFIG_FILE, 'w') as file:
			json.dump(Config.cfg, file)
	
	def get(key, default = None):
		Config.loadConfig()
		return Config.cfg.get(key, default)
	
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

class IntTableWidgetItem(QTableWidgetItem):
	""" A QTableWidgetItem with an int value.
		Overrides the __lt__ method for int instead of string value comparison.
	"""
	def __init__(self, int):
		super(IntTableWidgetItem, self).__init__(str(int))
		self.int = int
	def __lt__(self, other):
		if isinstance(other, QTableWidgetItem):
			return self.int < other.int
		return super(IntTableWidgetItem, self).__lt__(other)
	def setInt(self, int):
		self.int = int
		self.setText(str(int))
	def setData(self, role, value):
		if role == Qt.EditRole:
			self.int = int(value)
			super(IntTableWidgetItem, self).setData(role, str(self.int))
		else: super(IntTableWidgetItem, self).setData(role, value)

class HexBytesTableWidgetItem(QTableWidgetItem):
	""" A QTableWidgetItem for bytes representing a hex value.
		Overrides the __lt__ value comparison.
	"""
	def __init__(self, bytes):
		super(HexBytesTableWidgetItem, self).__init__(createHex(bytes))
		self.bytes = bytes
	def __lt__(self, other):
		if isinstance(other, HexBytesTableWidgetItem):
			if not self.bytes and other.bytes: return False
			if self.bytes and not other.bytes: return True
			if len(self.bytes) != len(other.bytes): return len(self.bytes) < len(other.bytes)
			return self.bytes < other.bytes
		return super(HexBytesTableWidgetItem, self).__lt__(other)
	def setBytes(self, bytes):
		self.bytes = bytes
		self.setText(createHex(bytes))
	def setData(self, role, value):
		if role == Qt.EditRole:
			self.bytes = parseHex(value)
			super(HexBytesTableWidgetItem, self).setData(role, createHex(self.bytes))
		else: super(HexBytesTableWidgetItem, self).setData(role, value)

class ListTableWidgetItem(QTableWidgetItem):
	""" A QTableWidgetItem for a special list representing a text value.
		Overrides the __lt__ value comparison.
	"""
	def __init__(self, lst):
		super(ListTableWidgetItem, self).__init__(list2text(lst))
		self.lst = lst
	def __lt__(self, other):
		if isinstance(other, ListTableWidgetItem):
			if not self.lst and other.lst: return False
			if self.lst and not other.lst: return True
			return list2text(self.lst) < list2text(other.lst)
		return super(ListTableWidgetItem, self).__lt__(other)
	def setList(self, lst):
		self.lst = lst
		self.setText(list2text(lst))
	def setData(self, role, value):
		if role == Qt.EditRole:
			self.lst = text2list(value)
			super(ListTableWidgetItem, self).setData(role, list2text(self.lst))
		else: super(ListTableWidgetItem, self).setData(role, value)


############
## Window ##
############

class Window(QMainWindow):
	""" The Main Window of the editor. """
	
	def __init__(self):
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
			'SEP':           None, # the current separator token
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
		
		# menu
		self.actionOpen.triggered.connect(self.openFile)
		self.actionSave.triggered.connect(self.saveFile)
		self.actionSaveAs.triggered.connect(self.saveFileAs)
		self.actionImport.triggered.connect(self.importFile)
		self.actionExport.triggered.connect(self.exportFile)
		self.actionApplyPatch.triggered.connect(self.importPatch)
		self.actionCreatePatch.triggered.connect(self.exportPatch)
		self.actionSeparatorToken.triggered.connect(self.editSeparatorToken)
		
		self.actionHideEmptyTexts.setChecked(Config.get('hide-empty-texts', True))
		self.actionHideEmptyTexts.triggered.connect(self.filterData)
		
		self.actionFTPClient.triggered.connect(self.showFTPClient)
		
		self.actionAbout.triggered.connect(self.showAbout)
		self.actionCheckForUpdates.triggered.connect(lambda: self.checkUpdates(True))
		
		# decoding table
		self.menuDecodingTableGroup = QActionGroup(self.menuDecodingTable)
		self.menuDecodingTableGroup.addAction(self.actionDecodingTableFromSav) # table from save
		self.menuDecodingTableGroup.addAction(self.actionNoDecodingTable) # no table
		if not path.exists(TABLE_PATH): os.makedirs(TABLE_PATH) # create directory if missing
		for file in [f for f in os.listdir(TABLE_PATH) if path.splitext(f)[1] == '.txt']:
			file = path.join(TABLE_PATH, file)
			action = self.menuDecodingTable.addAction(file)
			action.setCheckable(True)
			self.menuDecodingTableGroup.addAction(action)
		self.menuDecodingTableGroup.triggered.connect(self.updateDecodingTable)
		self.updateDecodingTable(None) # select default
		
		# language
		self.menuLanguageGroup = QActionGroup(self.menuLanguage)
		self.menuLanguageGroup.addAction(self.actionGerman)
		self.menuLanguageGroup.addAction(self.actionEnglish)
		self.menuLanguageGroup.addAction(self.actionSpanish)
		self.menuLanguageGroup.triggered.connect(self.retranslateUi)
		
		# filter
		self.editFilter.setFixedWidth(280)
		self.editFilter.textChanged.connect(self.filterData)
		self.buttonFilter.setFixedWidth(20)
		self.buttonFilter.clicked.connect(self.editFilter.clear)
		
		# table
		self.table.setColumnCount(5)
		self.table.cellChanged.connect(self.tableCellChanged)
		self.table.cellDoubleClicked.connect(self.tableCellDoubleClicked)
		
		self.retranslateUi(None)
		self.setWindowIcon(QIcon(ICON))
		self.show()
		self.resizeTable()
		self.checkUpdates()
	
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
		self.setWindowTitle(self.tr('BinJEditor'))
		self.editFilter.setPlaceholderText(self.tr('Filter'))
		self.buttonFilter.setText(self.tr('⨉'))
		self.table.setHorizontalHeaderLabels([self.tr('id'), self.tr('orig.bytes'), self.tr('orig.text'), self.tr('edit.bytes'), self.tr('edit.text')])
		self.menuFile.setTitle(self.tr('File'))
		self.menuHelp.setTitle(self.tr('Help'))
		self.menuEdit.setTitle(self.tr('Edit'))
		self.menuDecodingTable.setTitle(self.tr('Decoding Table'))
		self.menuView.setTitle(self.tr('View'))
		self.menuTools.setTitle(self.tr('Tools'))
		self.menuSettings.setTitle(self.tr('Settings'))
		self.menuLanguage.setTitle(self.tr('Language'))
		self.actionOpen.setText(self.tr('Open...'))
		self.actionAbout.setText(self.tr('About BinJ Editor...'))
		self.actionCheckForUpdates.setText(self.tr('Check for Updates...'))
		self.actionImport.setText(self.tr('Import...'))
		self.actionExport.setText(self.tr('Export...'))
		self.actionSave.setText(self.tr('Save'))
		self.actionSaveAs.setText(self.tr('Save As...'))
		self.actionCreatePatch.setText(self.tr('Create patch...'))
		self.actionApplyPatch.setText(self.tr('Apply patch...'))
		self.actionHideEmptyTexts.setText(self.tr('Hide empty texts'))
		self.actionDecodingTableFromSav.setText(self.tr('Table from Save'))
		self.actionSeparatorToken.setText(self.tr('Separator Token...'))
		self.actionFTPClient.setText(self.tr('Send via FTP...'))
		self.actionNoDecodingTable.setText(self.tr('No table'))
	
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
				if showFailure: self.showInfo(self.tr('update.newestVersion') % self.tr('appname'))
				return
			
			if current_version > tag_version:
				if showFailure: self.showInfo(self.tr('update.newerVersion') % self.tr('appname'))
				return
			
			# show message
			msg = QMessageBox()
			msg.setWindowTitle(self.tr('Check for Updates...'))
			msg.setWindowIcon(QIcon(ICON))
			text = '<html><body><p>%s</p><p>%s: <code>%s</code><br/>%s: <code>%s</code></p><p>%s</p></body></html>'
			msg.setText(text % (self.tr('update.newVersionAvailable') % self.tr('appname'), self.tr('update.currentVersion'), VERSION, self.tr('update.newVersion'), tag, self.tr('update.doWhat')))
			info = re.sub(r'\[([^\]]*)\]\([^)]*\)', '\\1', info) # remove links
			info = re.sub(r'__([^_\r\n]*)__|_([^_\r\n]*)_|\*\*([^\*\r\n]*)\*\*|\*([^\*\r\n]*)\*|`([^`\r\n]*)`', '\\1\\2\\3\\4\\5', info) # remove bold, italic and inline code
			msg.setDetailedText(info)
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
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return
		
		# ask filename
		dir = Config.get('sav-dir', None)
		if dir and not path.exists(dir): dir = None
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('open'), dir, self.tr('type.savj_save') + ';;' + self.tr('type.savj') + ';;' + self.tr('type.save'))
		if not filename: return
		_, type = path.splitext(filename)
		Config.set('sav-dir', path.dirname(filename))
		self.updateFilename(filename, True)
		
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
	
	def saveFile(self):
		""" Saves the current .savJ or .savE file. """
		self.updateFilename(self.info['filename'], True)
		self._saveFile(self.info['filename'])
		return True
	
	def saveFileAs(self):
		""" Saves a .savJ or .savE file. """
		# ask filename
		dir = Config.get('sav-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.splitext(self.info['filename'])[0]
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('saveAs'), dir, {'binJ': self.tr('type.savj'), 'e': self.tr('type.save')}[self.info['mode']])
		if not filename: return False
		Config.set('sav-dir', path.dirname(filename))
		self.updateFilename(filename, True)
		# save savJ or savE
		self._saveFile(filename)
		return True
	
	def _saveFile(self, filename):
		""" Implements the saving of .savJ and .savE files.
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
		with open(orig_filename, 'w', encoding = 'ASCII') as file:
			file.write(origj)
		edit_filename = path.join(tempdir(), 'edit.datJ')
		with open(edit_filename, 'w', encoding = 'ASCII') as file:
			file.write(editj)
		sep_filename = path.join(tempdir(), 'SEP.bin')
		with open(sep_filename, 'wb') as file:
			file.write(self.info['SEP'])
		special_filename = path.join(tempdir(), 'special.tabJ')
		with open(special_filename, 'w', encoding = 'UTF-8') as file:
			file.write(specialj)
		decode_filename = path.join(tempdir(), 'decode.tabJ')
		with open(decode_filename, 'w', encoding = 'ASCII') as file:
			file.write(decodej)
		encode_filename = path.join(tempdir(), 'encode.tabJ')
		with open(encode_filename, 'w', encoding = 'ASCII') as file:
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
			with open(header_filename, 'w', encoding = 'ASCII') as file:
				file.write(header)
			scripts = createSpt(self.extra['scripts'])
			scripts_filename = path.join(tempdir(), 'scripts.spt')
			with open(scripts_filename, 'w', encoding = 'ASCII') as file:
				file.write(scripts)
			links = createTabE(self.extra['links'])
			links_filename = path.join(tempdir(), 'links.tabE')
			with open(links_filename, 'w', encoding = 'ASCII') as file:
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
	
	def importFile(self):
		""" Imports a .binJ or .e file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return
		# ask filename
		dir = Config.get('import-file-dir', None)
		if dir and not path.exists(dir): dir = None
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('import'), dir, self.tr('type.binj_e') + ';;' + self.tr('type.binj') + ';;' + self.tr('type.e'))
		if not filename: return
		_, type = path.splitext(filename)
		Config.set('import-file-dir', path.dirname(filename))
		self.updateFilename(filename, False)
		
		# load sep from config
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
		except:
			self.showError(self.tr('error.importFailed'))
			self.info['filename'] = None
			self.info['mode'] = None
			self.info['SEP'] = None
			self.data = None
			self.extra = dict()
			self.updateFilename(None)
			self.setData(list())
	
	def exportFile(self):
		""" Exports a .binJ or .e file. """
		dir = Config.get('export-file-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.splitext(self.info['filename'])[0]
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.binj'), 'e': self.tr('type.e')}[self.info['mode']])
		if not filename: return False
		Config.set('export-file-dir', path.dirname(filename))
		
		# create data
		data = [edit if edit else orig for orig, _, edit, _ in self.data]
		
		# save data
		if self.info['mode'] == 'binJ':
			bin = createBinJ(data, self.info['SEP'], self.extra)
			with open(filename, 'wb') as file: file.write(bin)
		elif self.info['mode'] == 'e':
			bin = createE(data, self.info['SEP'], self.extra)
			with GzipFile(filename, 'w') as file: file.write(bin)
		
		return True
	
	def importPatch(self):
		""" Imports a patch from a .patJ / .patE or compatible .binJ / .e file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return
		# ask filename
		dir = Config.get('import-patch-dir', None)
		if dir and not path.exists(dir): dir = None
		extensions = {
			'binJ': self.tr('type.patj_binj') + ';;' + self.tr('type.patj') + ';;' + self.tr('type.binj'),
			'e':    self.tr('type.pate_e')    + ';;' + self.tr('type.pate') + ';;' + self.tr('type.e')
		}[self.info['mode']]
		filename, _ = QFileDialog.getOpenFileName(self, self.tr('import'), dir, extensions)
		if not filename: return
		_, type = path.splitext(filename)
		Config.set('import-patch-dir', path.dirname(filename))
		
		# import from patj / pate
		if type.lower() in ['.patj', '.pate']:
			with open(filename, 'r', encoding = 'ASCII') as file:
				patch = file.read()
			edit_data = parseDatJ(patch)
			
			# check if compatible
			if len(edit_data) != len(self.data):
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return
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
				else: return # abort
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
				return
			
			# check if compatible
			if len(edit_data) != len(self.data): # check data length
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return
				# trim or pad edit data
				if len(edit_data) > len(self.data): edit_data = edit_data[:len(self.data)]
				else: edit_data = edit_data + [b'']*(len(self.data) - len(edit_data))
			
			# check if compatible for binj
			if self.info['mode'] == 'binJ':
				if extra['prefix'] != self.extra['prefix']:
					# prefixes do not match -> show warning and ask to continue
					if not self.askWarning(self.tr('warning.prefixesDiffer')): return
			
			# check if compatible for binj
			elif self.info['mode'] == 'e':
				# something does not match -> show warning and ask to continue
				if extra['prefix'] != self.extra['prefix']:
					if not self.askWarning(self.tr('warning.prefixesDiffer')): return
				if extra['header'] != self.extra['header']:
					if not self.askWarning(self.tr('warning.HeadersDiffer')): return
				if extra['scripts'] != self.extra['scripts']:
					if not self.askWarning(self.tr('warning.ScriptsDiffer')): return
				if extra['links'] != self.extra['links']:
					if not self.askWarning(self.tr('warning.LinksDiffer')): return
			
			# set data
			orig_data = [bytes for bytes, _, _, _ in self.data]
			edit_data = [edit if edit != orig else b'' for orig, edit in zip(orig_data, edit_data)] # filter equal elements
			self.updateFilename() # show file changed
			self.setData(orig_data, edit_data)
	
	def exportPatch(self):
		""" Exports a patch file as a .patJ or .patE file. """
		dir = Config.get('export-patch-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.splitext(self.info['filename'])[0]
		filename, _ = QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.patj'), 'e': self.tr('type.pate')}[self.info['mode']])
		if not filename: return False
		_, type = path.splitext(filename)
		Config.set('export-patch-dir', path.dirname(filename))
		
		# create patch
		patch = createDatJ([bytes for _, _, bytes, _ in self.data])
		
		# save patJ or patE
		with open(filename, 'w', encoding = 'ASCII') as file:
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
		msg.setText(text % (self.tr('appname'), VERSION, 'https://github.com/%s' % REPOSITORY, 'GitHub', AUTHOR, self.tr('about.specialThanks') % SPECIAL_THANKS))
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
			self.setWindowTitle('%s%s - %s' % ('*' if self.flag['changed'] else '', path.basename(self.info['filename']), self.tr('appname')))
		else: self.setWindowTitle(self.tr('appname'))
		# activate actions
		actions_enabled = self.info['filename'] is not None
		self.actionSaveAs.setEnabled(actions_enabled)
		self.actionExport.setEnabled(actions_enabled)
		self.actionApplyPatch.setEnabled(actions_enabled)
		self.actionCreatePatch.setEnabled(actions_enabled)
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
			if default: idx = next((i for i, a in enumerate(self.menuDecodingTableGroup.actions()) if a.text() == default), -1)
			else: idx = -1
			# else use first res or no table
			if idx == -1: idx = 2 if len(self.menuDecodingTableGroup.actions()) >= 3 else 1
			action = self.menuDecodingTableGroup.actions()[idx]
			action.setChecked(True)
			if action is self.actionNoDecodingTable:
				self.info['decodingTable'] = {'encode': dict(), 'decode': dict(), 'special': dict()}
			else: self.info['decodingTable'] = parseDecodingTable(action.text())
		
		# arg is normal option -> select option by given filename
		else:
			filename = arg.text()
			Config.set('decoding-table', filename)
			action = next(action for action in self.menuDecodingTableGroup.actions() if action.text() == filename)
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
		number_width = 40
		scrollbar_width = 20
		self.table.setColumnWidth(0, number_width)
		column_width = int((self.table.width() - self.table.verticalHeader().width() - number_width - scrollbar_width) / 4)
		for i in range(1, 5):
			self.table.setColumnWidth(i, column_width)
	
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
			# id
			item = IntTableWidgetItem(i+1)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 0, item)
			# original bytes
			item = HexBytesTableWidgetItem(orig_key)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 1, item)
			# original text
			item = ListTableWidgetItem(orig_value)
			item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
			self.table.setItem(row, 2, item)
			# edit bytes
			item = HexBytesTableWidgetItem(edit_key)
			self.table.setItem(row, 3, item)
			# edit text
			item = ListTableWidgetItem(edit_value)
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
		if hideEmpty != Config.get('hide-empty-texts', True): Config.set('hide-empty-texts', hideEmpty)
		
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
		id = self.table.item(row, 0).int - 1 # logical row
		
		# edit bytes
		if column == 3:
			bytes = bytes_cell.bytes
			lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # convert to list
		
		# edit text
		if column == 4:
			lst = list_cell.lst
			# convert to bytes
			try:
				bytes = list2bytes(lst, self.info['decodingTable'], self.info['SEP'])
				lst = bytes2list(bytes, self.info['decodingTable'], self.info['SEP']) # de-escape chars
			except Exception as e:
				self.showError(self.tr('error.unknownChar') % e.args[0])
				self.flag['editing'] = True
				list_cell.setList(self.data[id][3])
				self.flag['editing'] = False
				return
		
		# change data and cells
		self.flag['editing'] = True
		self.updateFilename()
		bytes_cell.setBytes(bytes)
		list_cell.setList(lst)
		self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
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
			for i, (r, c) in enumerate(indices):
				if len(content) == 1: text = content[0] # always use single line
				elif i < len(content): text = content[i] # use next line
				else: break # stop pasting
				
				bytes_cell = self.table.item(r, 3)
				list_cell  = self.table.item(r, 4)
				id = self.table.item(r, 0).int - 1 # logical row
				
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
						list_cell.setList(self.data[id][3])
						self.flag['editing'] = False
						break # break loop
				
				# change data and cells
				self.flag['editing'] = True
				self.updateFilename()
				bytes_cell.setBytes(bytes)
				list_cell.setList(lst)
				self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
				self.flag['editing'] = False
		
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
			for r in rows:
				# copy
				if s != '': s += linesep # go to next row
				for j, c in enumerate(columns):
					text = self.table.item(r, c).text()
					if j: s += '\t' # go to next column
					s += text
				
				# clear
				id = self.table.item(r, 0).int - 1 # logical row
				self.flag['editing'] = True
				self.updateFilename()
				self.table.item(r, 3).setBytes(b'')
				self.table.item(r, 4).setList(list())
				self.data[id] = (self.data[id][0], self.data[id][1], b'', list())
				self.flag['editing'] = False
			
			# copy to clipboard
			clipboard.copy(s)
			return
		
		# Del -> clear
		if Qt.Key_Delete in keys:
			# collect indices for pasting
			indices = [(ind.row(), ind.column()) for ind in self.table.selectedIndexes()] # get selection
			indices = [(r, c) for r, c in indices if c in [3, 4]] # filter selection for editable columns
			rows = {r for r, _ in indices} # collect rows
			
			for r in sorted(rows):
				id = self.table.item(r, 0).int - 1 # logical row
				self.flag['editing'] = True
				self.updateFilename()
				self.table.item(r, 3).setBytes(b'')
				self.table.item(r, 4).setList(list())
				self.data[id] = (self.data[id][0], self.data[id][1], b'', list())
				self.flag['editing'] = False
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
		id = self.table.item(row, 0).int - 1 # logical row
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
		self.table.item(row, 3).setBytes(bytes)
		self.table.item(row, 4).setList(lst)
		self.data[id] = (self.data[id][0], self.data[id][1], bytes, lst)
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
			with GzipFile(filename, 'w') as file: file.write(bin)
		
		# open ftp client and pass the temporary filename
		dlg = FTPClient(filename)
		dlg.exec_()
		
		# delete temporary binj file
		os.remove(filename)
		pass


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
		elif type.lower() == '.e' and name.startswith('demo'): mode = 'Demo/e'
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


##########
## Main ##
##########

if __name__ == '__main__':
	app = QApplication(sys.argv)
	translator = QTranslator()
	baseTranslator = QTranslator()
	ICON = QPixmap(':/Resources/Images/icon.ico')
	window = Window()
	window.resizeTable()
	app.exec_()
