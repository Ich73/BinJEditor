""" Author: Dominik Beese
>>> BinJ Editor
	An editor for .binJ and .e files with custom decoding tables.
<<<
"""

# pip install pyqt5
# pip install pyperclip
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QEvent
from PyQt5.uic import loadUi
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
from functools import cmp_to_key

TABLE_FOLDER = 'Table'
CONFIG_FILENAME = 'config.json'

APPNAME = 'BinJ Editor'
VERSION = 'v2.2.0'
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

class DataTableWidgetItem(QtWidgets.QTableWidgetItem):
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
		if isinstance(other, QtWidgets.QTableWidgetItem):
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

class PathTableWidgetItem(DataTableWidgetItem):
	""" A QTableWidgetItem with a path value. """
	def __init__(self, data, parent):
		self.parent = path.normpath(parent)
		super(PathTableWidgetItem, self).__init__(path.normpath(data))
	def data2text(self, data):
		return path.relpath(data, path.commonprefix((data, self.parent)))
	def text2data(self, text):
		return path.join(self.parent, text)


###########
## TABLE ##
###########

def createHex(bytes):
	""" Example: '\xa4\x08' -> 'A4 08' """
	return ' '.join(['%02X' % b for b in bytes])

def parseHex(s):
	""" Example: 'A4 08' -> '\xa4\x08' """
	s = ''.join(c for c in s if c in set('0123456789ABCDEFabcdef'))
	return bytes([int(s[i:i+2], 16) for i in range(0, len(s), 2)])

class EditorTable(QtWidgets.QTableView):
	""" A table view as the main editor. """
	
	KEYS_PRESSED = set()
	
	def __init__(self, parent):
		super(EditorTable, self).__init__()
		self.parent = parent
		# set model and delegate
		self.setModel(EditorTableModel(self))
		self.setItemDelegate(EditorItemDelegate(self))
		# connect signals
		self.doubleClicked.connect(self.cellDoubleClicked)
		# set behaviour
		self.setSelectionMode(QtWidgets.QAbstractItemView.ContiguousSelection)
		self.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
		self.sortByColumn(0, Qt.AscendingOrder)
		# change color palette
		palette = QtGui.QPalette()
		alternateBaseColor = QtGui.QColor(243, 243, 243) # alternating row colors
		palette.setColor(QtGui.QPalette.Active,   QtGui.QPalette.AlternateBase, alternateBaseColor)
		palette.setColor(QtGui.QPalette.Inactive, QtGui.QPalette.AlternateBase, alternateBaseColor)
		inactiveHighlightColor = palette.color(QtGui.QPalette.Active, QtGui.QPalette.Highlight) # inactive highlight
		inactiveHighlightColor.setAlpha(30)
		palette.setColor(QtGui.QPalette.Inactive, QtGui.QPalette.Highlight, inactiveHighlightColor)
		self.setPalette(palette)
	
	## EVENTS ##
	
	def keyPressEvent(self, event):
		""" Custom key press event. """
		super(EditorTable, self).keyPressEvent(event)
		self.KEYS_PRESSED.add(event.key())
		if self.currentIndex(): self.cellKeyPressed(self.currentIndex(), self.KEYS_PRESSED)
	
	def keyReleaseEvent(self, event):
		""" Custom key release event. """
		super(EditorTable, self).keyReleaseEvent(event)
		self.KEYS_PRESSED.discard(event.key())
	
	def cellDoubleClicked(self, index):
		""" Called when a cell is double clicked to copy orig to edit. """
		row, col = index.row(), index.column()
		if col in [1, 2] and not self.model().hasEditData(row):
			self.model().copy(row)
			self.parent.updateFilename()
	
	def cellKeyPressed(self, index, keys):
		""" Called when keys are pressed for copy, paste etc. """
		# parse index
		row, col = index.row(), index.column()
		
		# Ctrl+C -> copy
		if {Qt.Key_Control, Qt.Key_C} == keys:
			# get selection
			indices = [(ind.row(), ind.column()) for ind in self.selectedIndexes()]
			# create copy string
			s, lr = ('', None)
			for r, c in sorted(indices):
				text = self.data(r, c, role = Qt.DisplayRole)
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
			content = clipboard.paste().splitlines() # get clipboard content as lines
			
			# collect indices
			indices = [(ind.row(), ind.column()) for ind in self.selectedIndexes()] # get selection
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
				if not self.model().setData(self.model().index(r, c), text, role = Qt.EditRole): break
				self.parent.updateFilename()
			return
		
		# Ctrl+X -> cut
		if {Qt.Key_Control, Qt.Key_X} == keys:
			# collect indices
			indices = [(ind.row(), ind.column()) for ind in self.selectedIndexes()] # get selection
			columns = sorted({c for _, c in indices}) # collect columns to copy
			rows = sorted({r for r, c in indices if c in [3, 4]}) # collect rows to cut, only editable columns
			if not rows: return
			
			# create copy string and clear data
			s = ''
			for r in rows:
				# copy
				if s != '': s += linesep # go to next row
				for j, c in enumerate(columns):
					text = self.data(r, c, role = Qt.DisplayRole)
					text = text.replace('\n', '')
					if j: s += '\t' # go to next column
					s += text
				
				# clear
				self.parent.updateFilename()
				self.model().setEditData(r, b'')
			
			# copy to clipboard
			clipboard.copy(s)
			return
		
		# Del -> clear
		if Qt.Key_Delete in keys:
			# collect rows to clear
			indices = [(ind.row(), ind.column()) for ind in self.selectedIndexes()] # get selection
			indices = [(r, c) for r, c in indices if c in [3, 4]] # filter selection for editable columns
			rows = {r for r, _ in indices} # collect rows
			# clear rows
			for r in sorted(rows):
				self.parent.updateFilename()
				self.model().setEditData(r, b'')
			return
		
		# Return/Enter -> next cell
		if Qt.Key_Return in keys or Qt.Key_Enter in keys:
			if Qt.Key_Shift in keys: # + Shift -> next empty cell or end
				next_row = next((r for r in range(row + 1, self.rowCount()) if not self.isRowHidden(r) and not self.model().hasEditData(r)), -1)
				if next_row == -1: next_row = next((r for r in range(self.rowCount()-1, row-1, -1) if not self.isRowHidden(r)), row)
			else: next_row = next((r for r in range(row + 1, self.rowCount()) if not self.isRowHidden(r)), row)
			self.setCurrentIndex(self.model().index(next_row, col))
			return
	
	## DATA ##
	
	def setData(self, orig_data, edit_data):
		""" Sets the data to the given [orig_data] and [edit_data]. """
		self.model().updateData(orig_data, edit_data)
		self.setSortingEnabled(not not orig_data)
	
	def data(self, row, col, role = Qt.DisplayRole):
		""" Returns the data at the given [row] and [col]. """
		return self.model().data(self.model().index(row, col), role = role)
	
	def origData(self):
		""" Returns the orig data in order (not as displayed). """
		return self.model().origData()
	
	def editData(self):
		""" Returns the edit data in order (not as displayed). """
		return self.model().editData()
	
	def rowCount(self):
		""" Returns the number of rows. """
		return self.model().rowCount()
	
	def columnCount(self):
		""" Returns the number of columns. """
		return self.model().columnCount()
	
	def autoScaleRows(self):
		return self.parent.actionScaleRowsToContents.isChecked()
	
	## ACTIONS ##
	
	def filterData(self):
		""" Filters the data. Does only search orig and edit text. """
		filter = self.parent.editFilter.text()
		hideEmpty = self.parent.actionHideEmptyTexts.isChecked()
		
		# prepare filter
		pattern = re.compile(re.escape(filter).replace('\\*', '.*'), re.IGNORECASE)
		
		# show and hide rows
		for row in range(self.rowCount()):
			visible = True
			if not any(pattern.search(self.model().data(self.model().index(row, col), role = Qt.DisplayRole).replace('\n', '')) for col in [2, 4]): visible = False # apply filter
			if hideEmpty and not self.model().hasOrigData(row) and not self.model().hasEditData(row): visible = False # apply hide empty
			if visible:
				if self.isRowHidden(row):
					self.showRow(row)
					if self.autoScaleRows(): self.resizeRowToContents(row)
			else:
				if not self.isRowHidden(row):
					self.hideRow(row)
		
		# scroll to selection
		QtCore.QTimer.singleShot(10, self.goToSelection) # wait for scrollbar
	
	def goToLine(self, line):
		""" Scrolls the table to the given [line]. """
		self.clearSelection()
		line2row = {self.data(r, 0, role = Qt.UserRole): r for r in range(self.rowCount()) if not self.isRowHidden(r) and self.data(r, 0, role = Qt.UserRole) >= line}
		if line2row:
			new_row = sorted(line2row.items())[0][1]
			self.setCurrentIndex(self.model().index(new_row, 4))
		self.goToSelection()
	
	def goToSelection(self):
		""" Scrolls the table to the selection if anything is selected. """
		index = self.currentIndex()
		if index is None: return
		self.scrollTo(index, QtWidgets.QAbstractItemView.PositionAtCenter)
	
	def resizeColumnsToContents(self):
		""" Resizes the columns. """
		self.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents) # fit first column to contents
		self.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch) # stretch last column to whole width
		for column in range(self.model().columnCount()): # set widths of all columns based on the item delegate
			sizeHint = self.itemDelegate().sizeHint(None, column)
			self.setColumnWidth(column, sizeHint.width())
	
	def setExpertModeEnabled(self, enabled):
		""" Enables or disables expert mode. """
		# show or hide columns
		self.setColumnHidden(1, not enabled)
		self.setColumnHidden(3, not enabled)
		# resize columns and rows
		self.resizeColumnsToContents()
		if self.autoScaleRows(): self.resizeRowsToContents()
	
	def clearCache(self):
		self.model().clearCache()

class EditorItemDelegate(QtWidgets.QStyledItemDelegate):
	""" An item delegate for the main editor. """
	
	def __init__(self, parent):
		super(EditorItemDelegate, self).__init__()
		self.parent = parent
	
	def editorEvent(self, event, model, option, index):
		""" Called when a table cell is triggered. """
		self.editorEvent = event.type() # store event type for setEditorData
		return False
	
	def createEditor(self, parent, option, index):
		""" Called to create an editor for editing a cell. """
		editor = QtWidgets.QPlainTextEdit(parent)
		editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # disable both scrollbars
		editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		return editor
	
	def setEditorData(self, editor, index):
		""" Called to put the initial text in the editor. """
		if self.editorEvent == QEvent.KeyPress: editor.setPlainText('') # clear text if entered by key press
		else: editor.setPlainText(index.data()) # else insert text
		if editor.height() <= 24: editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap) # disable word wrap if single line text
		editor.moveCursor(QtGui.QTextCursor.End) # move cursor to end of text
	
	def setModelData(self, editor, model, index):
		""" Called when commitData is called. """
		new_data = editor.toPlainText()
		if index.data() != new_data: model.setData(index, editor.toPlainText())
	
	def eventFilter(self, editor, event):
		""" Called when a key event occurs while editing. """
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
			# Escape -> keep original text, close editor
			elif event.key() == Qt.Key_Escape:
				self.closeEditor.emit(editor)
				return True
		return super(EditorItemDelegate, self).eventFilter(editor, event)
	
	def sizeHint(self, option, index):
		""" Called to get the size for the given index. """
		# parse index
		col = index if isinstance(index, int) else index.column()
		row = -1 if isinstance(index, int) else index.row()
		size = QtCore.QSize(0, 0)
		
		# auto-height text columns
		if row >= 0 and col in [2, 4]:
			height = super(EditorItemDelegate, self).sizeHint(option, index).height()
			if height > 24: height += 9 # increase height to make cell heigh enough for editing
			size.setHeight(height)
		
		# auto-width middle columns
		if col in [1, 2, 3]:
			stretched_columns = sum(1 for c in range(1, self.parent.columnCount()) if not self.parent.isColumnHidden(c))
			total_width = self.parent.viewport().size().width()
			number_width = self.parent.horizontalHeader().sectionSize(0)
			column_width = int((total_width - number_width) / stretched_columns)
			size.setWidth(column_width)
		
		# return default size
		return size

class EditorTableModel(QtCore.QAbstractTableModel):
	""" A table model for the main editor. """
	
	CACHE = dict()
	
	def __init__(self, parent):
		super(EditorTableModel, self).__init__()
		self.parent = parent
		self.inds = list()
		self.orig = list()
		self.edit = list()
	
	## DATA ##
	
	def updateData(self, orig, edit):
		""" Overrides the data with the given [edit] and [orig] data. """
		# update data
		self.orig = orig
		self.edit = edit if edit is not None else [b'']*len(self.orig)
		self.inds = list(range(len(self.orig)))
		# signal finish
		self.modelReset.emit()
		return True
	
	def origData(self):
		""" Returns the orig data in order (not as displayed). """
		return [self.orig[self.inds.index(i)] for i in range(len(self.inds))]
	
	def editData(self):
		""" Returns the edit data in order (not as displayed). """
		return [self.edit[self.inds.index(i)] for i in range(len(self.inds))]
	
	def data2bytes(self, data):
		return createHex(data)
	
	def bytes2data(self, bytes):
		return parseHex(bytes)
	
	def data2text(self, data):
		# check cache
		if data in self.CACHE: # cache hit > use it
			lst = self.CACHE[data]
		else: # cache miss > convert to list and store
			lst = bytes2list(data, self.parent.parent.info['decodingTable'], self.parent.parent.info['SEP'])
			self.CACHE[data] = lst
		
		# convert to text
		if self.parent.autoScaleRows():
			t = ''
			for char in lst:
				if isinstance(char, str): t += char # normal case
				else: # special case
					if t and char[0] in ['SEP', 'LF']: t += '\n' # extra linebreak before
					t += '[%s]' % char[0]
					if char[0] in ['SEP']: t += '\n' # extra linebreak after
			return t
		else: return list2text(lst)
	
	def text2data(self, text):
		lst = text2list(text.replace('\n', ''))
		return list2bytes(lst, self.parent.parent.info['decodingTable'], self.parent.parent.info['SEP'])
	
	def setEditData(self, row, data):
		""" Sets the edit data of the given [row] to [data]. """
		self.edit[row] = data
		self.dataChanged.emit(self.index(row, 3), self.index(row, 4), [Qt.EditRole])
		if self.parent.autoScaleRows(): self.parent.resizeRowToContents(row)
	
	def hasOrigData(self, row):
		""" Returns true if the orig data in the given [row] is not empty. """
		return self.orig[row] != b''
	
	def hasEditData(self, row):
		""" Returns true if the edit data in the given [row] is not empty. """
		return self.edit[row] != b''
	
	def clearCache(self):
		self.CACHE.clear()
	
	## TABLE MODEL ##
	
	def headerData(self, section, orientation = Qt.Horizontal, role = Qt.DisplayRole):
		""" Sets the text in the header of the table. """
		if role != Qt.DisplayRole: return QtCore.QVariant()
		# horizontal header -> title texts
		if orientation == Qt.Horizontal:
			if section == 0: return self.tr('line')
			if section == 1: return self.tr('orig.bytes')
			if section == 2: return self.tr('orig.text')
			if section == 3: return self.tr('edit.bytes')
			if section == 4: return self.tr('edit.text')
		# vertical header -> numbers
		if orientation == Qt.Vertical:
			return int(section+1)
	
	def setData(self, index, value, role = Qt.EditRole):
		""" Sets the data at the given [index] to the given [value]. """
		# get index
		row, col = index.row(), index.column()
		
		# edit data
		if col == 3: # bytes
			data = self.bytes2data(value)
		if col == 4: # text
			try:
				data = self.text2data(value)
			except Exception as e:
				self.parent.parent.showError(self.tr('error.unknownChar') % e.args[0])
				return False
		
		# udpate data
		self.edit[row] = data
		self.dataChanged.emit(self.index(row, 3), self.index(row, 4), [role])
		self.parent.parent.updateFilename()
		if self.parent.autoScaleRows(): self.parent.resizeRowToContents(row)
		return True
	
	def data(self, index, role = Qt.DisplayRole):
		""" Returns the data at the given [index].
			If Qt.DisplayRole is given texts are returned.
			If Qt.UserRole is given int and bytes are returned.
		"""
		# parse index
		row, col = index.row(), index.column()
		
		# DisplayRole -> str
		if role == Qt.DisplayRole:
			if col == 0: return str(self.inds[row]+1)
			if col == 1: return self.data2bytes(self.orig[row])
			if col == 2: return self.data2text(self.orig[row])
			if col == 3: return self.data2bytes(self.edit[row])
			if col == 4: return self.data2text(self.edit[row])
		
		# UserRole -> int/bytes
		elif role == Qt.UserRole:
			if col == 0: return self.inds[row]+1
			if col in [1, 2]: return self.orig[row]
			if col in [3, 4]: return self.edit[row]
	
	def flags(self, index):
		""" Returns the flags for the given index. """
		# default -> enabled and selectable
		f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
		# edit data -> + editable
		if index.column() in [3, 4]: f |= Qt.ItemIsEditable
		return f
	
	def sort(self, column, order):
		""" Sorts the data in the table based on the given [column] and [order]. """
		def comparator(x, y):
			""" Returns 1 if x > y else -1. """
			# parse inputs
			(x, _), (y, _) = x, y
			# line column -> int
			if column == 0: return 1 if x < y else -1
			# bytes column -> bytes
			if column in [1, 3]:
				if not x and y: return -1
				if x and not y: return 1
				if len(x) != len(y): return 1 if len(x) < len(y) else -1 # prioritize length
				return 1 if x < y else -1
			# text column > str
			if column in [2, 4]:
				if not x and y: return -1
				if x and not y: return 1
				return 1 if self.data2text(x) < self.data2text(y) else -1
		
		# sort data according to column
		keys = [(self.data(self.index(row, column), role = Qt.UserRole), row) for row in range(self.rowCount())]
		keys = sorted(keys, key = cmp_to_key(comparator), reverse = order == Qt.AscendingOrder)
		
		# shuffle data according to keys
		self.inds = [self.inds[i] for _, i in keys]
		self.orig = [self.orig[i] for _, i in keys]
		self.edit = [self.edit[i] for _, i in keys]
		
		# update row height and visibility
		rowHeights = [self.parent.rowHeight(i) for _, i in keys]
		hiddenRows = {j for j, (_, i) in enumerate(keys) if self.parent.isRowHidden(i)}
		for row, height in enumerate(rowHeights):
			if row in hiddenRows: self.parent.hideRow(row)
			else: self.parent.showRow(row)
			self.parent.setRowHeight(row, height)
		
		# signal
		self.modelReset.emit()
	
	def copy(self, row):
		""" Copies the orig data in the given [row] to the edit data. """
		self.edit[row] = self.orig[row]
		self.dataChanged.emit(self.index(row, 3), self.index(row, 4), [Qt.EditRole])
		if self.parent.autoScaleRows(): self.parent.resizeRowToContents(row)
	
	def rowCount(self, index = None):
		""" Returns the number of rows. """
		return len(self.orig)
	
	def columnCount(self, index = None):
		""" Returns the number of columns. """
		return 5


############
## Window ##
############

class Window(QtWidgets.QMainWindow):
	""" The Main Window of the editor. """
	
	def __init__(self, load_file = None):
		super(Window, self).__init__()
		uiFile = QtCore.QFile(':/Resources/Forms/window.ui')
		uiFile.open(QtCore.QFile.ReadOnly)
		loadUi(uiFile, self)
		uiFile.close()
		
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
			'loading': False, # while something is loading to prevent update filname
		}
		self.cache = {
			'decodingTableFromSave': None, # the decoding table of the loaded save file
		}
		
		# data
		self.extra = {
			# 'prefix': None,  # the prefix bytes
			# 'header': None,  # for e files
			# 'scripts': None, # for e files
			# 'links': None,   # for e files
		}
		
		# dialogs
		self.dialogs = list()
		
		# table
		self.table = EditorTable(self)
		self.centralWidget().layout().addWidget(self.table)
		
		# menu > file
		self.actionOpen.triggered.connect(self.openFile)
		self.actionOpen.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
		self.actionSave.triggered.connect(self.saveFile)
		self.actionSave.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
		self.actionSaveAs.triggered.connect(self.saveFileAs)
		self.actionSaveAs.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
		self.actionClose.triggered.connect(self.closeFile)
		self.actionClose.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogCloseButton))
		self.actionImport.triggered.connect(self.importFile)
		self.actionImport.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowLeft))
		self.actionExport.triggered.connect(self.exportFile)
		self.actionExport.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowRight))
		self.actionApplyPatch.triggered.connect(self.importPatch)
		self.actionCreatePatch.triggered.connect(self.exportPatch)
		
		# menu > edit
		self.menuDecodingTableGroup = QtWidgets.QActionGroup(self.menuDecodingTable)
		self.menuDecodingTable.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView))
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
		self.actionGoToLine.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaSeekForward))
		
		# menu > view
		self.actionHideEmptyTexts.setChecked(Config.get('hide-empty-texts', True))
		self.actionHideEmptyTexts.triggered.connect(lambda value: Config.set('hide-empty-texts', value))
		self.actionHideEmptyTexts.triggered.connect(self.table.filterData)
		self.actionScaleRowsToContents.setChecked(Config.get('scale-rows-to-contents', True))
		self.actionScaleRowsToContents.triggered.connect(lambda value: Config.set('scale-rows-to-contents', value))
		self.actionScaleRowsToContents.triggered.connect(self.resizeTable)
		self.actionAlternatingRowColors.setChecked(Config.get('alternating-row-colors', True))
		self.table.setAlternatingRowColors(Config.get('alternating-row-colors', True))
		self.actionAlternatingRowColors.triggered.connect(lambda value: Config.set('alternating-row-colors', value))
		self.actionAlternatingRowColors.triggered.connect(self.table.setAlternatingRowColors)
		self.actionExpertMode.setChecked(Config.get('expert-mode', False))
		self.table.setExpertModeEnabled(Config.get('expert-mode', False))
		self.actionExpertMode.triggered.connect(lambda value: Config.set('expert-mode', value))
		self.actionExpertMode.triggered.connect(self.table.setExpertModeEnabled)
		
		# menu > tools
		self.actionFTPClient.triggered.connect(self.showFTPClient)
		self.actionFTPClient.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DriveNetIcon))
		self.actionSearchDlg.triggered.connect(self.showSearchDlg)
		self.actionSearchDlg.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView))
		
		# menu > settings
		self.menuLanguageGroup = QtWidgets.QActionGroup(self.menuLanguage)
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
		self.actionAbout.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation))
		self.actionCheckForUpdates.triggered.connect(lambda: self.checkUpdates(True))
		self.actionCheckForUpdates.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
		
		# filter
		self.editFilter.setFixedWidth(280)
		self.editFilter.textChanged.connect(self.table.filterData)
		self.buttonFilter.setFixedWidth(20)
		self.buttonFilter.clicked.connect(self.editFilter.clear)
		
		# ui
		self.retranslateUi(None)
		self.setWindowIcon(QtGui.QIcon(ICON))
		if Config.get('expert-mode', False): self.resize(1080, 600)
		else: self.resize(880, 512)
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
			locale = Config.get('language', QtCore.QLocale.system().name().split('_')[0])
			if not QtCore.QFile.exists(':/Resources/i18n/%s.qm' % locale): locale = 'en'
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
		self.actionAlternatingRowColors.setText(self.tr('Alternating Row Colors'))
		self.actionExpertMode.setText(self.tr('Expert Mode'))
		self.actionDecodingTableFromSav.setText(self.tr('Table from Save'))
		self.actionSeparatorToken.setText(self.tr('Separator Token...'))
		self.actionFTPClient.setText(self.tr('Send via FTP...'))
		self.actionSearchDlg.setText(self.tr('Search in Files...'))
		self.actionNoDecodingTable.setText(self.tr('No Table'))
	
	def resizeEvent(self, newSize):
		""" Called when the window is resized. """
		self.resizeTable()
	
	def closeEvent(self, event):
		""" Called when the window is about to close. """
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
			msg = QtWidgets.QMessageBox()
			msg.setWindowTitle(self.tr('Check for Updates...'))
			msg.setWindowIcon(QtGui.QIcon(ICON))
			text = '<html><body><p>%s</p><p>%s: <code>%s</code><br/>%s: <code>%s</code></p><p>%s</p></body></html>'
			msg.setText(text % (self.tr('update.newVersionAvailable') % APPNAME, self.tr('update.currentVersion'), VERSION, self.tr('update.newVersion'), tag, self.tr('update.doWhat')))
			info = re.sub(r'!\[([^\]]*)\]\([^)]*\)', '', info) # remove images
			info = re.sub(r'\[([^\]]*)\]\([^)]*\)', '\\1', info) # remove links
			info = re.sub(r'__([^_\r\n]*)__|_([^_\r\n]*)_|\*\*([^\*\r\n]*)\*\*|\*([^\*\r\n]*)\*|`([^`\r\n]*)`', '\\1\\2\\3\\4\\5', info) # remove bold, italic and inline code
			msg.setDetailedText(info.strip())
			button_open_website = QtWidgets.QPushButton(self.tr('update.openWebsite'))
			msg.addButton(button_open_website, QtWidgets.QMessageBox.AcceptRole)
			msg.addButton(QtWidgets.QMessageBox.Cancel)
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
		filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, self.tr('open'), dir, self.tr('type.savj_save') + ';;' + self.tr('type.savj') + ';;' + self.tr('type.save'))
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
		self.flag['loading'] = True
		self.cache['decodingTableFromSave'] = decodingTable
		self.info['SEP'] = SEP
		self.updateDecodingTable(self.actionDecodingTableFromSav)
		self.flag['loading'] = False
		self.table.clearCache()
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
		filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, self.tr('saveAs'), dir, {'binJ': self.tr('type.savj'), 'e': self.tr('type.save')}[self.info['mode']])
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
		origj = createDatJ(self.table.origData())
		editj = createDatJ(self.table.editData())
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
		self.extra = dict()
		self.updateFilename(None)
		self.table.clearCache()
		self.setData(list())
		return True
	
	def importFile(self):
		""" Imports a .binJ or .e file. """
		# ask if file was changed
		if self.flag['changed'] and not self.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		# ask filename
		dir = Config.get('import-file-dir', ROOT)
		if dir and not path.exists(dir): dir = ROOT
		filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, self.tr('import'), dir, self.tr('type.binj_e') + ';;' + self.tr('type.binj') + ';;' + self.tr('type.e'))
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
			self.table.clearCache()
			self.setData(orig_data)
			return True
		except:
			self.showError(self.tr('error.importFailed'))
			self.info['filename'] = None
			self.info['mode'] = None
			self.info['SEP'] = None
			self.extra = dict()
			self.updateFilename(None)
			self.table.clearCache()
			self.setData(list())
			return False
	
	def exportFile(self):
		""" Exports a .binJ or .e file. """
		dir = Config.get('export-file-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.join(ROOT, path.splitext(self.info['filename'])[0])
		filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.binj'), 'e': self.tr('type.e')}[self.info['mode']])
		if not filename: return False
		Config.set('export-file-dir', path.dirname(filename))
		return self._exportFile(filename)
	
	def _exportFile(self, filename):
		""" Implements exporting of .binJ and .e files. """
		# create data
		data = [edit if edit else orig for orig, edit in zip(self.table.origData(), self.table.editData())]
		
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
		filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, self.tr('import'), dir, extensions)
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
			if len(edit_data) != self.table.rowCount():
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return False
				# trim or pad edit data
				if len(edit_data) > self.table.rowCount(): edit_data = edit_data[:self.table.rowCount()]
				else: edit_data = edit_data + [b'']*(self.table.rowCount() - len(edit_data))
			
			# set data
			orig_data = self.table.origData()
			self.updateFilename() # show file changed
			self.setData(orig_data, edit_data)
		
		# import from binj / e file
		elif type.lower() in ['.binj', '.e']:
			# check separator
			if self.info['SEP'] != parseHex(Config.get('SEP', 'E31B')):
				# different tokens -> ask which one to use
				sep_from_settings = Config.get('SEP', 'E31B')
				sep_from_current_file = createHex(self.info['SEP']).replace(' ', '')
				msg = QtWidgets.QMessageBox()
				msg.setIcon(QtWidgets.QMessageBox.Critical)
				msg.setWindowTitle(self.tr('warning'))
				msg.setWindowIcon(QtGui.QIcon(ICON))
				msg.setText(self.tr('warning.differentSeparatorTokens') % (sep_from_settings, sep_from_current_file))
				button_from_settings = QtWidgets.QPushButton(sep_from_settings)
				button_from_current_file = QtWidgets.QPushButton(sep_from_current_file)
				msg.addButton(button_from_settings, QtWidgets.QMessageBox.AcceptRole)
				msg.addButton(button_from_current_file, QtWidgets.QMessageBox.AcceptRole)
				msg.addButton(QtWidgets.QMessageBox.Cancel)
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
			if len(edit_data) != self.table.rowCount(): # check data length
				# lengths differ -> show warning and ask to continue
				if not self.askWarning(self.tr('warning.lengthsDiffer')): return False
				# trim or pad edit data
				if len(edit_data) > self.table.rowCount(): edit_data = edit_data[:self.table.rowCount()]
				else: edit_data = edit_data + [b'']*(self.table.rowCount() - len(edit_data))
			
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
			orig_data = self.table.origData()
			edit_data = [edit if edit != orig else b'' for orig, edit in zip(orig_data, edit_data)] # filter equal elements
			self.updateFilename() # show file changed
			self.setData(orig_data, edit_data)
			return True
	
	def exportPatch(self):
		""" Exports a patch file as a .patJ or .patE file. """
		dir = Config.get('export-patch-dir', None)
		if dir and path.exists(dir): dir = path.join(dir, path.splitext(path.basename(self.info['filename']))[0])
		else: dir = path.join(ROOT, path.splitext(self.info['filename'])[0])
		filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, self.tr('export'), dir, {'binJ': self.tr('type.patj'), 'e': self.tr('type.pate')}[self.info['mode']])
		if not filename: return False
		_, type = path.splitext(filename)
		Config.set('export-patch-dir', path.dirname(filename))
		return self._exportPatch(filename)
	
	def _exportPatch(self, filename):
		""" Implements exporting of .patJ and .patE files. """
		# create patch
		patch = createDatJ(self.table.editData())
		
		# save patJ or patE
		with open(filename, 'w', encoding = 'ASCII', newline = '\n') as file:
			file.write(patch)
		return True
	
	## DIALOGS ##
	
	def showAbout(self):
		""" Displays the about window. """
		msg = QtWidgets.QMessageBox()
		msg.setIconPixmap(ICON.scaledToWidth(112))
		msg.setWindowTitle(self.tr('about.title'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		text = '''<html><body style="text-align: center; font-size: 10pt">
					<p><b style="font-size: 14pt">%s </b><b>%s</b>
					<br/>@ <a href="%s">%s</a></p>
					<p style="text-align: center;">%s</p>
					<p>%s</p>
				</body></html>'''
		msg.setText(text % (APPNAME, VERSION, 'https://github.com/%s' % REPOSITORY, 'GitHub', AUTHOR, self.tr('about.specialThanks') % SPECIAL_THANKS))
		msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
		msg.exec_()
	
	def editSeparatorToken(self):
		""" Shows a dialog to update the separator token. """
		dlg = QtWidgets.QInputDialog()
		dlg.setWindowFlags(Qt.WindowCloseButtonHint)
		dlg.setWindowTitle(self.tr('settings'))
		dlg.setWindowIcon(QtGui.QIcon(ICON))
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
		""" Shows a dialog to scroll to a certain line. """
		dlg = QtWidgets.QInputDialog()
		dlg.setInputMode(QtWidgets.QInputDialog.IntInput)
		dlg.setIntMinimum(1)
		dlg.setIntMaximum(self.table.rowCount())
		dlg.setWindowFlags(Qt.WindowCloseButtonHint)
		dlg.setWindowTitle(self.tr('Go to Line...'))
		dlg.setWindowIcon(QtGui.QIcon(ICON))
		dlg.setLabelText(self.tr('dlg.goToLine'))
		current_index = self.table.currentIndex()
		line = current_index.row()+1 if current_index is not None else 1
		dlg.setIntValue(line)
		if not dlg.exec_(): return
		self.table.goToLine(dlg.intValue())
	
	def showError(self, text, detailedText = None):
		""" Displays an error message. """
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Critical)
		msg.setWindowTitle(self.tr('error'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
		msg.exec_()
	
	def showWarning(self, text, detailedText = None):
		""" Displays a warning message. """
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
		msg.exec_()
	
	def askWarning(self, text, detailedText = None):
		""" Displays a warning message and asks yes or no.
			Returns True if yes was selected.
		"""
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
		return msg.exec_() == QtWidgets.QMessageBox.Yes
	
	def askSaveWarning(self, text):
		""" Displays a warning message and asks yes, no or cancel.
			If yes was chosen, the current file will be saved.
			Returns True if the file was successfully saved or No was chosen.
		"""
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Warning)
		msg.setWindowTitle(self.tr('warning'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel)
		res = msg.exec_()
		if res == QtWidgets.QMessageBox.Yes:
			# yes -> save or saveAs
			# return True if progress was saved
			if self.flag['savable']:
				self.saveFile()
				return True
			else:
				return self.saveFileAs()
		elif res == QtWidgets.QMessageBox.No:
			# no -> return True
			return True
		elif res == QtWidgets.QMessageBox.Cancel:
			# cancel -> return False
			return False
	
	def showInfo(self, text, detailedText = None):
		""" Displays a warning message. """
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Information)
		msg.setWindowTitle(self.tr('information'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
		msg.exec_()
	
	## PROPERTIES ##
	
	def updateFilename(self, filename = None, savable = None):
		""" Called when a new file is loaded or an edit is made.
			Updates the changed flag and filename info variabe.
			Enables the actionSave option.
			Sets the correct title of the window.
		"""
		# normalize path
		if filename is not None: filename = path.normpath(filename)
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
			# clear table cache
			self.table.clearCache()
			# not loading -> show file changed
			if not self.flag['loading']: self.updateFilename()
			# file loaded -> update data
			if self.table.rowCount(): self.setData(self.table.origData(), self.table.editData())
	
	def resizeTable(self):
		""" Resizes the table.
			The columns are distributed equally.
		"""
		# resize columns
		self.table.resizeColumnsToContents()
		
		# resize rows
		if self.actionScaleRowsToContents.isChecked(): self.table.resizeRowsToContents()
		else: self.table.verticalHeader().setDefaultSectionSize(self.table.verticalHeader().minimumSectionSize())
		
		# scroll to selection
		self.table.goToSelection()
	
	## DATA ##
	
	def setData(self, orig_data, edit_data = None):
		""" Sets the data from the given prefix, original bytes and edited bytes.
			Updates the data.
			Resizes the table by calling self.resizeTable().
		"""
		# prepare loading
		self.editFilter.clear()
		oldLength = self.table.rowCount()
		oldLine = self.table.currentIndex().row()+1 if self.table.currentIndex() is not None else 1
		
		# add new data
		self.table.setData(orig_data, edit_data)
		
		# finish loading
		self.resizeTable()
		if self.table.rowCount() == oldLength: # if data is similar
			self.table.goToLine(oldLine) # scroll to old selection
		QtCore.QTimer.singleShot(20, self.resizeTable) # wait for scrollbar
		self.table.filterData() # filter data
	
	## MISC ##
	
	def showFTPClient(self):
		""" Creates and shows the FTP Client. """
		# create temporary binj or e file
		data = [edit if edit else orig for orig, edit in zip(self.table.origData(), self.table.editData())]
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
		""" Creates and shows a Search Dialog. """
		dlg = SearchDlg(self.info['SEP'], self)
		self.dialogs.append(dlg)
		dlg.exec_()
		self.dialogs.remove(dlg)


################
## FTP Client ##
################

class FTPClient(QtWidgets.QDialog):
	""" The dialog for sending files using FTP. """
	
	def __init__(self, filename):
		""" filename - the full filename of the file to send
			           AND the filename guess for the destination file
		"""
		super(FTPClient, self).__init__()
		uiFile = QtCore.QFile(':/Resources/Forms/ftpclient.ui')
		uiFile.open(QtCore.QFile.ReadOnly)
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
		self.editPort.setValidator(QtGui.QIntValidator(0, 9999))
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
		self.editTitleID.setValidator(QtGui.QRegExpValidator(QtCore.QRegExp('[0-9a-fA-F]{16}')))
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
		self.setWindowIcon(QtGui.QIcon(ICON))
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
			QtWidgets.QApplication.processEvents()
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

class SearchDlg(QtWidgets.QDialog):
	""" The dialog for searching texts in files. """
	
	def __init__(self, SEP, parent):
		super(SearchDlg, self).__init__()
		self.parent = parent
		uiFile = QtCore.QFile(':/Resources/Forms/searchdlg.ui')
		uiFile.open(QtCore.QFile.ReadOnly)
		loadUi(uiFile, self)
		uiFile.close()
		
		self.setWindowFlags(Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
		self.SEP = SEP or b'\xe3\x1b'
		
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
		for item in Config.get('search.filter.history', list()): self.cbFilter.addItem(item)
		self.cbFilter.setEditText(Config.get('search.filter', '*'))
		self.cbFilter.editTextChanged.connect(lambda value: Config.set('search.filter', value))
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
		
		# table
		self.table.cellDoubleClicked.connect(self.tableCellDoubleClicked)
		
		self.retranslateUi()
		self.setWindowIcon(QtGui.QIcon(ICON))
		self.show()
		self.resizeTable()
	
	def retranslateUi(self):
		self.setWindowTitle(self.tr('Search in Files...'))
		self.labelSettings.setText(self.tr('Search Settings'))
		self.labelSearchFor.setText(self.tr('Search for:'))
		self.useRegex.setText(self.tr('Regex'))
		self.labelDirectory.setText(self.tr('Directory:'))
		self.labelFilter.setText(self.tr('Filter:'))
		self.labelFiles.setText(self.tr('Files:'))
		self.labelDecodingTable.setText(self.tr('Table:'))
		self.buttonSearch.setText(self.tr('Search'))
		self.table.setHorizontalHeaderLabels([self.tr('file'), self.tr('line'), self.tr('text')])
		self.table.setSortingEnabled(True)
		self.updateCBFiles()
	
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
	
	def tableCellDoubleClicked(self, row, column):
		""" Called when a table cell is double clicked. """
		# check which line was double clicked
		filename = self.table.item(row, 0).data()
		line = self.table.item(row, 1).data()
		
		# file is current file -> go to line
		if filename == self.parent.info['filename']:
			self.parent.table.goToLine(line)
			return
		
		# file is another file -> ask for saving
		if self.parent.flag['changed'] and not self.parent.askSaveWarning(self.tr('warning.saveBeforeOpening')): return False
		
		# open other file and go to line
		_, type = path.splitext(filename)
		if type.lower() in ['.savj', '.save']: self.parent._openFile(filename)
		elif type.lower() in ['.binj', '.e']: self.parent._importFile(filename)
		else:
			self.showError(self.tr('error.cannotOpenPatchFiles'))
			return
		self.parent.table.goToLine(line)
	
	def showError(self, text, detailedText = None):
		""" Displays an error message. """
		msg = QtWidgets.QMessageBox()
		msg.setIcon(QtWidgets.QMessageBox.Critical)
		msg.setWindowTitle(self.tr('error'))
		msg.setWindowIcon(QtGui.QIcon(ICON))
		msg.setText(text)
		if detailedText: msg.setDetailedText(detailedText)
		msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
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
		dir = QtWidgets.QFileDialog.getExistingDirectory(self, self.tr('chooseDirectory'), self.cbDirectory.currentText())
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
		self.cbFilter.setEnabled(not self.searching)
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
		fileNameFilter = self.cbFilter.currentText() or '*'
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
				searchStringPattern = re.compile(searchString)
			except Exception as e:
				self.showError(self.tr('error.invalidRegex'), str(e))
				self.toggleSearch(False)
				return
		else:
			searchStringPattern = re.compile(re.escape(searchString).replace('\\*', '.*'), re.IGNORECASE)
		if fileNameFilter not in ['', '*']:
			fileNamePattern = re.compile('^%s$' % re.escape(fileNameFilter).replace('\\*', '.*'), re.IGNORECASE)
		else: fileNamePattern = None
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
		updateHistory(self.cbFilter, 'search.filter.history')
		
		# collect all files, idle animation
		self.progressBar.setMaximum(0)
		QtWidgets.QApplication.processEvents()
		filenames = list()
		for dp, _, fn in os.walk(directory):
			for f in fn:
				if path.splitext(f)[1] not in fileTypes: continue
				if fileNamePattern and not fileNamePattern.search(path.splitext(path.basename(f))[0]) and not fileNamePattern.search(path.basename(f)): continue
				filenames.append(path.join(dp, f))
				QtWidgets.QApplication.processEvents()
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
					QtWidgets.QApplication.processEvents()
				
				# search texts
				for i, line in enumerate(texts):
					if not searchStringPattern.search(line): continue
					
					# add row
					row = self.table.rowCount()
					self.table.insertRow(row)
					# file
					item = PathTableWidgetItem(filename, directory)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 0, item)
					# line
					item = IntTableWidgetItem(i+1)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 1, item)
					# text
					item = QtWidgets.QTableWidgetItem(line)
					item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
					self.table.setItem(row, 2, item)
			
			# update progress bar
			self.progressBar.setValue(ctr+1)
			QtWidgets.QApplication.processEvents()
		
		# complete search
		self.toggleSearch(False)


##########
## Main ##
##########

if __name__ == '__main__':
	app = QtWidgets.QApplication(list())
	translator = QtCore.QTranslator()
	baseTranslator = QtCore.QTranslator()
	ICON = QtGui.QPixmap(':/Resources/Images/icon.ico')
	filename = sys.argv[1] if len(sys.argv) > 1 else None
	window = Window(filename)
	window.resizeTable()
	app.exec_()
