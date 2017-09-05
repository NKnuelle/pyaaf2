
from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
    )

from StringIO import StringIO
from .utils import (
    read_u8,
    read_u16le,
    read_u32le,
    write_u8,
    write_u16le,
    write_u32le,
    mangle_name,
    )

SF_DATA                                   = 0x82
SF_DATA_STREAM                            = 0x42
SF_STRONG_OBJECT_REFERENCE                = 0x22
SF_STRONG_OBJECT_REFERENCE_VECTOR         = 0x32
SF_STRONG_OBJECT_REFERENCE_SET            = 0x3A
SF_WEAK_OBJECT_REFERENCE                  = 0x02
SF_WEAK_OBJECT_REFERENCE_VECTOR           = 0x12
SF_WEAK_OBJECT_REFERENCE_SET              = 0x1A
SF_WEAK_OBJECT_REFERENCE_STORED_OBJECT_ID = 0x03
SF_UNIQUE_OBJECT_ID                       = 0x86
SF_OPAQUE_STREAM                          = 0x40

# not sure about these
SF_DATA_VECTOR                            = 0xD2
SF_DATA_SET                               = 0xDA

PROPERTY_VERSION=32

class PropertyItem(object):
    def __init__(self, root, pid, format, version=PROPERTY_VERSION):
        self.root = root
        self.pid = pid
        self.format = format
        self.version = version

    def format_name(self):
        return str(property_formats[self.format].__name__)

    @property
    def propertydef(self):
        classdef = self.root.classdef
        if classdef is None:
            return

        for p in classdef.all_propertydefs():
            if p.pid == self.pid:
                return p
    @property
    def name(self):
        propertydef = self.propertydef
        if propertydef:
            return propertydef.property_name

    @property
    def typedef(self):
        propertydef = self.propertydef
        if propertydef:
            return propertydef.typedef

    @property
    def value(self):
        try:
            return self.typedef.decode(self.data)
        except:
            print("0x%x" % self.format)
            print(self)
            print(self.root.dir.path())
            raise


    def __repr__(self):
        return "0x%04X %s" % (self.pid, self.format_name())


class SFData(PropertyItem):
    def decode(self, data=None):
        self.data = data

    def __repr__(self):
        name = self.name
        if name:
            return "<%s %s>" % (name, str(self.typedef))
        else:
            return "<%s %d bytes>" % (self.__class__.__name__, len(self.data))

class SFStream(SFData):
    def decode(self, data=None):
        for i, c in enumerate(reversed(data)):
            if c != '\0':
                break

        self.stream_name = data[1:].decode("utf-16-le")

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, str(self.stream_name))

    @property
    def value(self):
        return self.root.dir.get(self.stream_name)


# abtract for refereneces
class SFObjectRef(SFData):
    pass

# abtract for referenece arrays
class SFObjectRefArray(SFObjectRef):
    pass

class SFStrongRef(SFObjectRef):
    def __init__(self, root, pid, format, version=PROPERTY_VERSION):
        super(SFStrongRef, self).__init__(root, pid, format, version)
        self.ref = None
        self.object = None

    def decode(self, data):
        self.data = data
        #null terminated
        self.ref = data[:-2].decode("utf-16le")

    def encode(self, data):
        return data.encode("utf-16le") + b"\x00" + b"\x00"

    def __repr__(self):
        return "<%s %s to %s>" % (self.name, self.__class__.__name__, str(self.ref))

    @property
    def value(self):
        if self.object:
            return self.object
        dir_entry = self.root.dir.get(self.ref)
        if dir_entry:
            self.object = self.root.root.read_object(dir_entry)
        return self.object


    @value.setter
    def value(self, value):

        typedef = self.typedef
        classdef = typedef.ref_classdef

        if value.classdef != classdef:
            raise Exception("must be instance of: %s" % classedef.class_name)

        if self.ref is None:
            propdef = self.propertydef
            self.ref = mangle_name(propdef.property_name, self.pid, 32)
            self.data = self.encode(self.ref)

        self.object = value
        if not self.pid in self.root.property_entries:
            self.root.property_entries[self.pid] = self

        # attach
        if self.root.dir:
            dir_entry = self.root.dir.get(self.ref)
            if dir_entry is None:
                dir_entry = self.root.dir.makedir(self.ref)

            value.attach(dir_entry)

# abtract for referenece arrays
class SFStrongRefArray(SFObjectRefArray):
    pass

class SFStrongRefVector(SFStrongRefArray):
    def decode(self, data):
        self.references = []
        self.ref = None
        #null terminated
        self.ref = data[:-2].decode("utf-16le")
        self.objects = []

    # def read_index(self):
        if not self.ref:
            return

        index_name = self.ref + " index"
        index_dir = self.root.dir.get(index_name)
        if not index_dir:
            raise Exception()

        f = index_dir.open('r')
        count = read_u32le(f)
        next_free_key = read_u32le(f)
        last_free_key = read_u32le(f)

        for i in range(count):
            local_key = read_u32le(f)
            ref = "%s{%x}" % (self.ref, local_key)
            # print(i, count, ref)
            self.references.append(ref)

    @property
    def value(self):
        if self.objects:
            return self.objects

        references = []
        for ref in self.references:
            dir_entry = self.root.dir.get(ref)
            item = self.root.root.read_object(dir_entry)
            references.append(item)
        self.objects = references
        return references

    def __repr__(self):
        return "<%s %s to %s %d items>" % (self.name, self.__class__.__name__, str(self.ref), len(self.references))


class SFStrongRefSet(SFStrongRefArray):
    def __init__(self, root, pid, format, version=PROPERTY_VERSION):
        super(SFStrongRefSet, self).__init__(root, pid, format, version)
        self.references = {}
        self.ref = None
        self.objects = {}
        self.local_map = {}
        self.next_free_key = 0
        self.last_free_key = 0
        self.key_size = 0
        self.index_pid = 0

    def encode(self, data):
        return data.encode("utf-16le") + b"\x00" + b"\x00"

    def decode(self, data):
        self.data = data
        self.references = {}
        self.ref = None
        self.ref = data[:-2].decode("utf-16le")
        self.objects = {}
        self.local_map = {}


        if not self.ref:
            return

        index_name = self.ref + " index"
        index_dir = self.root.dir.get(index_name)
        if not index_dir:
            raise Exception()

        f = index_dir.open('r')
        count = read_u32le(f)
        self.next_free_key = read_u32le(f)
        self.last_free_key = read_u32le(f)
        self.index_pid = read_u16le(f)
        self.key_size = read_u8(f)

        # f = StringIO(f.read())

        for i in range(count):
            local_key = read_u32le(f)
            ref_count = read_u32le(f)

            key = f.read(self.key_size).encode("hex")
            ref = "%s{%x}" % (self.ref, local_key)
            self.local_map[local_key] = ref
            self.references[key] = ref

    def write_index(self):
        f = self.root.dir.touch(self.ref + " index").open(mode='w')
        count = len(self.references)

        write_u32le(f, count)
        write_u32le(f, self.next_free_key)
        write_u32le(f, self.last_free_key)
        write_u16le(f, self.index_pid)
        write_u8(f, self.key_size)

        i = 0

        for key, value in self.references.items():
            write_u32le(f, i)
            write_u32le(f, 1)
            f.write(key.decode("hex"))

    def items(self):

        for key, ref in self.references.items():
            if key in self.objects:
                yield (key, self.objects[key])

            dir_entry = self.root.dir.get(ref)
            obj = self.root.root.read_object(dir_entry)
            self.objects[key] = obj

            yield (key, obj)

    @property
    def value(self):

        if len(self.objects) == len(self.references):
            return self.objects
        d = {}
        for key, ref in self.items():
            d[key] = ref
        self.objects = d
        return d

    @value.setter
    def value(self, value):
        typedef = self.typedef
        classdef = typedef.member_typedef.ref_classdef

        for key, obj in value.items():
            if not classdef.isinstance(obj.classdef):
                raise Exception()

        self.objects = value

        if self.ref is None:
            propdef = self.propertydef
            self.ref = mangle_name(propdef.property_name, self.pid, 32)
            self.data = self.encode(self.ref)

        # for key, obj in value.items():


        if not self.pid in self.root.property_entries:
            self.root.property_entries[self.pid] = self

    def attach(self):
        pass

    def __repr__(self):
        return "<%s to %s %d items>" % (self.__class__.__name__, str(self.ref), len(self.references))

class SFWeakRef(SFObjectRef):
    def decode(self, data):

        f = StringIO(data)

        self.ref_index = read_u16le(f)
        self.ref_pid = read_u16le(f)
        self.id_size = id_size = read_u8(f)
        self.ref = f.read(self.id_size).encode("hex")

    def __repr__(self):
        return "<%s %s index %s %s>" % (self.name, self.__class__.__name__, self.ref_index, self.ref)

    @property
    def value(self):
        return self.root.root.resovle_weakref(self.ref_index, self.ref_pid, self.ref)

class SFWeakRefArray(SFObjectRefArray):
    def decode(self, data):
        self.references = []
        #null terminated
        self.ref = data[:-2].decode("utf-16le")

        index_name = self.ref + " index"
        index_dir = self.root.dir.get(index_name)
        if not index_dir:
            raise Exception()

        f = index_dir.open('r')
        count = read_u32le(f)
        self.ref_index = read_u16le(f)
        self.ref_pid = read_u16le(f)
        self.id_size = read_u8(f)
        # print(self.pid)
        for i in range(count):
            identification = f.read(self.id_size).encode("hex")
            # print("  ",self.ref_index, identification)
            self.references.append(identification)

    def __repr__(self):
        return "<%s %s to %d items>" % (self.name, self.__class__.__name__, len(self.references) )


    @property
    def value(self):
        items = []
        for ref in self.references:
            r = self.root.root.resovle_weakref(self.ref_index, self.ref_pid, ref)
            items.append(r)
        return items

class SFWeakRefVector(SFWeakRefArray):
    pass
class SFWeakRefSet(SFWeakRefArray):
    pass


# haven't see aaf files that contain these yet
class SFWeakRefId(SFWeakRef):
    pass

class SFUniqueId(SFData):
    pass

class SFOpaqueStream(SFData):
    pass

property_formats = {
SF_DATA                                    : SFData,
SF_DATA_STREAM                             : SFStream,
SF_STRONG_OBJECT_REFERENCE                 : SFStrongRef,
SF_STRONG_OBJECT_REFERENCE_VECTOR          : SFStrongRefVector,
SF_STRONG_OBJECT_REFERENCE_SET             : SFStrongRefSet,
SF_WEAK_OBJECT_REFERENCE                   : SFWeakRef,
SF_WEAK_OBJECT_REFERENCE_VECTOR            : SFWeakRefVector,
SF_WEAK_OBJECT_REFERENCE_SET               : SFWeakRefSet,
SF_WEAK_OBJECT_REFERENCE_STORED_OBJECT_ID  : SFWeakRefId,
SF_UNIQUE_OBJECT_ID                        : SFUniqueId,
SF_OPAQUE_STREAM                           : SFOpaqueStream
}
