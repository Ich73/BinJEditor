""" Author: Dominik Beese """

def hex2bytes(s): return bytes([int(s[i:i+2], 16) for i in range(0, len(s), 2)])
def bytes2hex(bytes): return ''.join(['%02X' % b for b in bytes])
def invertDict(d):
	b = dict()
	for k, v in sorted(d.items(), key=lambda x: len(x[0])):
		if v not in b: b[v] = k
	return b


###########
## Table ##
###########

def parseDecodingTable(filename):
	""" Parses a decoding table where pairs of 'hex;char' are given.
		Special characters are surrounded by [].
		Characters that are surrounded by () are only used for byte to character conversion not vice versa.
		Returns a dict with decoding table 'decode', encoding table 'encode' and special symbols 'special'.
	"""
	decoding_table = dict()
	encoding_table = dict()
	special = dict()
	with open(filename, 'r', encoding = 'UTF-8') as file:
		for line in file:
			line = line[:-1] # remove newline
			if not line.strip() or line[0] == '#': continue # skip comments and empty lines
			key, value = line.split(';', 1)
			if value[0] == '[' and value[-1] == ']':
				# special character
				value = value[1:-1]
				special[hex2bytes(key)] = value
			elif value[0] == '(' and value[-1] == ')' and len(value) == 3:
				# decoding only
				value = value[1:-1]
				key = hex2bytes(key) # convert key to bytes
				value = value.encode('UTF-8') # convert value to bytes
				decoding_table[key] = value # add to decoding table
			else:
				# normal case
				key = hex2bytes(key) # convert key to bytes
				value = value.encode('UTF-8') # convert value to bytes
				decoding_table[key] = value # add to decoding table
				if value in encoding_table:
					print('Warning: Duplicate encoding for %s: %s and %s' % (value, encoding_table[value], key))
				encoding_table[value] = key # add to encoding table
	return {'decode': decoding_table, 'encode': encoding_table, 'special': special}


##########
## List ##
##########

def bytes2list(bin, decoding_table, separator_token):
	""" Converts a binary string into a list of characters using the given decoding table.
		The result contains either a string holding a single UTF-8 char or
		a tuple with a single element being a string representing a special character or byte value.
	"""
	table = decoding_table['decode']
	special = decoding_table['special'].copy() # copy so sep is not added permanently
	if separator_token not in special: special[separator_token] = 'SEP'
	max_length = len(max(table.keys(), key=len, default='1'))
	
	# decode
	lst = list()
	i = 0
	while i < len(bin):
		# try all byte lengths
		for b in range(max_length, 0, -1):
			if i + b > len(bin): continue
			key = bin[i:i+b]
			if key in special:
				# special character -> escape
				lst.append((special[key],))
				i += b
				break # skip else
			if key in table:
				# known key -> try encode unicode
				char = table[key]
				try:
					lst.append(char.decode('UTF-8'))
					i += b
					break # skip else
				except UnicodeDecodeError:
					# unicode failed -> escape each byte
					for c in char: lst.append(('%02X' % c,))
					i += b
					break # skip else
			# unknown key -> continue search
			else: continue
		else:
			# no key found -> escape it
			lst.append(('%02X' % bin[i],))
			i += 1
	return lst

def list2bytes(lst, decoding_table, separator_token):
	""" Converts a list of characters or single-element tuples to bytes. """
	def validHex(s): return all(c in '0123456789ABCDEFabcdef' for c in s)
	
	table = decoding_table['encode']
	special = invertDict(decoding_table['special']) # invert special
	if 'SEP' not in special: special['SEP'] = separator_token
	
	# encode
	bin = b''
	for char in lst: # every character in text
		if isinstance(char, tuple):
			# special case
			char = char[0]
			if validHex(char):
				# escape char
				bin += bytes([int(char, 16)])
				continue
			if char in special:
				# special character
				bin += special[char]
				continue
			else: raise Exception('[%s]' % char) # unknown char
				
		# normal case
		key = char.encode('UTF-8')
		if key not in table:
			raise Exception(char) # unknown char
		bin += table[key]
	return bin

def list2text(lst):
	""" Converts a list of characters or single-element tuples into a readable text.
		Special characters are printed insdie [].
	"""
	t = ''
	for char in lst:
		if isinstance(char, str): t += char # normal case
		else: t += '[%s]' % char[0] # special case
	return t

def text2list(text):
	""" Transforms a given text into a list of characters and single-element tuples. """
	def validHex(s): return all(c in '0123456789ABCDEFabcdef' for c in s)
	lst = list()
	i = 0
	while i < len(text):
		if text[i] == '[':
			# special case
			if i+3 < len(text) and validHex(text[i+1:i+3]) and text[i+3] == ']':
				# escaped byte
				lst.append((text[i+1:i+3].upper(),))
				i += 4
				continue
			j = text.find(']', i)
			if j != -1:
				# special character
				lst.append((text[i+1:j],))
				i += j-i+1
				continue
		# normal case
		lst.append(text[i])
		i += 1
	return lst


##########
## binJ ##
##########

def parseBinJ(binj, SEP):
	""" Parses the bytes data of a binj file by using the given separator token
		to separate the strings. More details of the algorithm used are given below.
	"""
	def pointer2bytes(ptr): return int.to_bytes(ptr, 4, 'little')
	def bytes2pointer(bytes): return int.from_bytes(bytes, 'little')
	
	# Note:
	# The parser tries to find the start of data by searching for the
	# first SEP char. Then it tries to find the start of the pointer
	# block by finding the pointer that points towards the position
	# of the previously searched first SEP char. If this succeeds the
	# parser parses every four bytes to a number, which gives the
	# next pointer. To determine the end of the pointer block it
	# checks if the parsed pointer value points towards a location
	# inside the file and makes sure the pointers are sorted ascending.
	# Otherwise this is not a valid pointer. If such a location is
	# found, this is not a pointer anymore and the list of pointers is
	# complete. If the first SEP char was a wrong char which can only
	# happen when a pointer has the same value as the SEP char, the
	# parser picks the next SEP char as the start of data.
	
	data_start = -1
	while True:
		# find start of pointer block
		data_start = binj.find(SEP, data_start+1)
		if data_start == -1: raise ValueError('Wrong SEP')
		pointer_start = binj.find(pointer2bytes(data_start + len(SEP)), 0, data_start)
		if pointer_start == -1: continue # a pointer is equal to SEP, choose next SEP as start
		
		pointer = list()
		# collect all pointers in pointer block
		for i in range(pointer_start, len(binj), 4):
			# read next pointer
			next_pointer = bytes2pointer(binj[i:i+4])
			if binj[next_pointer-len(SEP)-1:next_pointer-1] == SEP: next_pointer -= 1 # fix for 1-byte-off pointer
			# pointer must point inside file and be in ascending order
			if next_pointer > len(binj) or pointer and next_pointer < pointer[-1]: break
			# add pointer to list
			pointer.append(next_pointer)
		else: # reached end of file with pointers, no data, error
			raise ValueError('Wrong SEP')
		
		# add end of pointer block as first pointer
		pointer.insert(0, i)
		
		# get prefix
		prefix = binj[:pointer_start]
		
		# collect elements
		data = list()
		if pointer[-1] != len(binj): pointer.append(len(binj))
		for i in range(len(pointer)-1):
			ptr = pointer[i]
			next_ptr = pointer[i+1]
			data.append(binj[ptr:next_ptr-len(SEP)])
		
		# return prefix and data
		return (data, {'prefix': prefix})

def createBinJ(data, SEP, extra):
	""" Creates the bytes data for a binj file given a prefix, the data to include
		and the separator token to separate the strings.
	"""
	def pointer2bytes(ptr): return int.to_bytes(ptr, 4, 'little')
	
	# extract prefix
	prefix = extra['prefix']
	
	# add prefix
	binj = prefix
	
	# add pointer (first element without pointer)
	current_pointer = len(prefix) + (len(data)-1) * 4
	current_pointer += len(data[0]) + len(SEP)
	for elem in data[1:]:
		binj += pointer2bytes(current_pointer)
		current_pointer += len(elem) + len(SEP)
	
	# add data
	for elem in data:
		binj += elem
		binj += SEP
	
	# return binj
	return binj


#######
## e ##
#######

def parseE(bin, SEP):
	""" Parses the bytes data of an e file.
		Returns the following extra parameters:
		- prefix: the first four bytes
		- header: a list of script indices or None values
		- scripts: a list of (type, length, code) tuples
		- links: a dictionary from script index to script index
	"""
	def bytes2pointer(bytes): return int.from_bytes(bytes, 'little')
	TEXT_SCRIPTS = [0x43, 0x44, 0x84, 0x85]
	CODE_SCRIPTS = [0x0409, 0x040A, 0x040C, 0x040E]
	
	# collect magic number
	prefix = bin[:4]
	
	# parse scripts (first pass) and data
	scripts = list() # list of (type, length, code)
	pointers = dict() # temporary dict of index to pointer for linking code scripts
	offsets = list() # temporary list of offsets for linking
	data    = list()
	i = 0x1004
	while i < len(bin):
		offsets.append(i - 0x1004)
		type   = bytes2pointer(bin[i  :i+4])
		length = bytes2pointer(bin[i+4:i+8])
		code   = bin[i+8:i+length]
		if type in TEXT_SCRIPTS: # text scripts
			end = code.rfind(SEP) # find separator token
			if end == -1: end = len(code) # or use whole code
			data.append(code[:end])
			scripts.append((type, 0, b''))
		elif type in CODE_SCRIPTS: # code scripts
			pointer = bytes2pointer(code[:4])
			pointers[len(scripts)] = pointer
			code = b'\x00'*4 + code[4:]
			scripts.append((type, length, code))
		else: # other scripts
			scripts.append((type, length, code))
		i += length
	
	# parse header
	header = list() # list of script index or None
	for i in range(0x0004, 0x1004, 4):
		pointer = bytes2pointer(bin[i:i+4])
		if pointer == 0xFFFFFFFF:
			header.append(None)
			continue
		index = offsets.index(pointer)
		header.append(index)
	
	# link scripts (second pass)
	links = dict() # dict from script index to script index
	for i, (type, _, code) in enumerate(scripts):
		if type not in CODE_SCRIPTS: continue # code scripts
		pointer = pointers[i]
		index   = offsets.index(pointer)
		links[i] = index
	
	# return prefix, header, scripts, links and data
	return (data, {'prefix': prefix, 'header': header, 'scripts': scripts, 'links': links})

def createE(data, SEP, extra):
	""" Creates the bytes data for an e file given the data,
		separator token and extra information.
	"""
	def pointer2bytes(ptr): return int.to_bytes(ptr, 4, 'little')
	
	# extract prefix, header, scripts and links
	prefix  = extra['prefix']
	header  = extra['header']
	scripts = extra['scripts']
	links   = extra['links']
	
	# add data to scripts
	dataScripts = list()
	dataIdx = 0
	for type, length, code in scripts:
		if length == 0: # text script, generate code and length
			if len(data[dataIdx]) == 0: code = b'' # don't add SEP to empty texts
			else:
				code = data[dataIdx] + SEP # add data and separator token
				code += b'\x00' * (-len(code) % 4) # fill with zeros
			length = len(code) + 8 # plus 8 for type and length
			dataIdx += 1
		dataScripts.append((type, length, code))
	
	# calculate offsets for linking
	offsets = list()
	i = 0
	for _, length, _ in dataScripts:
		offsets.append(i)
		i += length
	
	# add magic bytes
	bin = prefix
	
	# add header
	for index in header:
		if index is None:
			bin += b'\xff'*4
			continue
		pointer = offsets[index]
		bin += pointer2bytes(pointer)
	
	# add scripts
	dataIdx = 0
	for i, (type, length, code) in enumerate(dataScripts):
		if i in links: # update pointers in code
			pointer = offsets[links[i]]
			code = pointer2bytes(pointer) + code[4:]			
		bin += pointer2bytes(type)
		bin += pointer2bytes(length)
		bin += code
	
	# return e content
	return bin


###########################
## Lists of Bytes (datJ) ##
###########################

def parseDatJ(datj):
	return [hex2bytes(hex) for hex in datj.splitlines()]

def createDatJ(data):
	return '\n'.join([bytes2hex(bin) for bin in data]) + '\n'


###########################
## Dicts of Bytes (tabJ) ##
###########################

def parseTabJ(tabj, hexValue = True):
	data = dict()
	for line in tabj.splitlines():
		k, v = line.split(';', 1)
		data[hex2bytes(k)] = hex2bytes(v) if hexValue else v
	return data

def createTabJ(data, hexValue = True):
	return '\n'.join('%s;%s' % (bytes2hex(k), bytes2hex(v) if hexValue else v) for k, v in data.items()) + '\n'


#########################
## Lists of Int (datE) ##
#########################

def parseDatE(date):
	return [int(s) if len(s) != 0 else None for s in date.splitlines()]

def createDatE(data):
	return '\n'.join([str(i) if i is not None else '' for i in data]) + '\n'


#########################
## Dicts of Int (tabE) ##
#########################

def parseTabE(tabe):
	data = dict()
	for line in tabe.splitlines():
		k, v = line.split(';', 1)
		data[int(k)] = int(v)
	return data

def createTabE(data):
	return '\n'.join('%d;%d' % (k, v) for k, v in data.items()) + '\n'


############################
## Lists of Scripts (spt) ##
############################

def parseSpt(spt):
	scripts = list()
	for line in spt.splitlines():
		type, length, code = line.split(';', 2)
		scripts.append((int(type), int(length), hex2bytes(code)))
	return scripts

def createSpt(scripts):
	spt = ''
	for type, length, code in scripts:
		spt += str(type)
		spt += ';'
		spt += str(length)
		spt += ';'
		spt += bytes2hex(code)
		spt += '\n'
	return spt
