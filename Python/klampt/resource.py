"""Use the get(), set(), and edit() functions to retrieve / store / edit
resources dynamically.

Use getDirectory() and setDirectory() to set the directory under which
resources are stored.  Alternatively, the directory=[DIRNAME] keyword
argument can be provided to get, set, and edit.

Example usage can be seen in demos/resourcetest.py.
"""

import loader
import trajectory
import multipath
import robotsim
import vectorops,se3,so3
import os
import time
from robotsim import WidgetSet,RobotPoser,ObjectPoser,TransformPoser,WorldModel,RobotModelLink,RigidObjectModel
from threading import Thread
from OpenGL.GL import *
from PyQt4.QtCore import *
from PyQt4.QtGui import *
import qtprogram
import gldraw

_directory = 'resources'

def getDirectory():
    """Returns the current resource directory."""
    return _directory

def setDirectory(value):
    """Sets the current resource directory."""
    global _directory
    _directory = value

def ensure_dir(f):
    d = os.path.dirname(f)
    if len(d)==0: return
    if not os.path.exists(d):
        os.makedirs(d)

extensionToType = {'.config':'Config',
                   '.configs':'Configs',
                   '.tri':'Geometry3D',
                   '.off':'Geometry3D',
                   '.stl':'Geometry3D',
                   '.poly':'Geometry3D',
                   '.geom':'GeometricPrimitive',
                   '.pcd':'Geometry3D',
                   '.vector3':'Vector3',
                   '.ikgoal':'IKGoal',
                   '.xform':'RigidTransform',
                   '.hold':'Hold',
                   '.stance':'Stance',
                   '.grasp':'Grasp'}

typeToExtension = dict((v,k) for (k,v) in extensionToType.items())


def filenameToType(name):
    fileName, fileExtension = os.path.splitext(name)
    if fileExtension in extensionToType:
        return extensionToType[fileExtension]
    elif fileExtension == '.xml':
        return 'xml'  #dynamic loading
    elif fileExtension == '.json':
        return 'json'  #dynamic loading
    else:
        raise RuntimeError("Cannot determine type of resource from name "+name)


def get(name,type='auto',directory=None,default=None,doedit='auto',description=None,editor='visual',world=None,frame=None):
    """Retrieve a resource of the given name from the current resources
    directory.  Resources may be of type Config, Configs, IKGoal, Hold,
    Stance, MultiPath, LinearPath, etc. (see Klampt/Modeling/Resources.h for
    a complete list; not all are supported in the Python API).  They can
    also be edited using RobotPose.

    If the resource does not already exist, an edit prompt will be
    shown, and the result from the prompt will be saved to disk under the
    given name.

    Arguments:
        - name: the resource name.  If type='auto', this is assumed to have
          a suffix of a file of the desired type.  The name can also be
          nested of the form 'group/subgroup/name.type'.
        - type: the resource type, or 'auto' to determine it automatically.
        - directory: the search directory.  If None, uses the current
          resource directory.
        - default: the default value if the resource does not exist on disk.
          If None, some arbitrary default value will be inferred.
        - doedit: if 'auto', if the resource does not exist on disk, an
          edit prompt will be displayed.  If False, an RuntimeError will be
          raised if the resource does not exist on disk.  If True, the
          user will be given an edit prompt to optionally edit the resource
          before this call returns.
        - description: an optional text description of the resource, for use
          in the edit prompt.
        - editor: either 'visual' or 'text', determining what to
        - world: for a visual editor, this world will be shown along with
          the item to edit.  If this is a string it points to a file
          that will be loaded for the world (e.g., a world XML file, or a
          robot file).
        - frame: for rigid transforms / rotations / points, the reference
          frame for the visual editor.  This is an element of se3.
          """
    if name==None:
        if doedit==False:
            raise RuntimeError("Can't get() an anonymous resource without launching editor")
        success,newvalue = edit(name,value=default,type=type,description=description,editor=editor,world=world,frame=frame)
        if not success:
            print "Cancel pressed, returning None"
            return None
        else:
            print "Ok pressed, returning anonymous resource"
            return newvalue
    if directory==None:
        directory = getDirectory()
    if type == 'auto':
        type = filenameToType(name)
    value = None
    try:
        fn = os.path.join(directory,name)
        if type == 'xml':
            raise NotImplementedError("TODO: load xml files from Python API")
        elif type == 'json':
            f = open(fn,'r')
            text = ''.join(f.readlines())
            f.close()
            value = loader.fromJson(text,type=type)
        else:
            value = loader.load(type,fn)
        if value==None:
            raise IOError
        if doedit==True:
            success,newvalue = edit(name,value=value,type=type,description=description,editor=editor,world=world,frame=frame)
            if success:
                print "Ok pressed, saving resource to",name
                value = newvalue
                set(name,value,type=type,directory=directory)
            else:
                print "Cancel pressed, not saving resource to disk"
            return value
        return value
    except IOError:
        if doedit!=False:
            print "Resource",fn,"does not exist, launching editor..."
            success,newvalue = edit(name,value=default,type=type,description=description,editor=editor,world=world,frame=frame)
            if success:
                print "Ok pressed, saving resource to",name
                value = newvalue
                set(name,value=value,type=type,directory=directory)
            else:
                print "Cancel pressed, not saving resource to disk"
            return value
        else:
            raise RuntimeError("Resource "+name+" does not exist")
    return

def set(name,value,type='auto',directory=None):
    """Saves a resource to disk under the given name."""
    if type == 'auto':
        type = filenameToType(name)
    if directory==None:
        directory = getDirectory()    
    fn = os.path.join(directory,name)
    ensure_dir(fn)
    if type == 'xml':
        raise NotImplementedError("TODO: save xml files from Python API")
    elif type == 'json':
        f = open(fn,'w')
        f.write(loader.toJson(value,type=type))
        f.write('\n')
        f.close()
        return True
    else:
        return loader.save(value,type,fn)

class VisualEditorBase:
    """A base class for editing resources."""
    def __init__(self,name,value,description,world):
        self.name = name
        self.value = value
        self.description = description
        self.world = world
        self.qtwidget = None
        self.width = 100
        self.height = 100
        self.klamptwidgetbutton = 2
        self.klamptwidgetmaster = WidgetSet()
        self.klamptwidgetdragging = False
        #refresh appearances for new OpenGL context
        #for i in xrange(world.numIDs()):
        #    world.appearance(i).refresh()
    def addWidget(self,widget):
        self.klamptwidgetmaster.add(widget)
    def instructions(self):
        return None
    def display(self):
        if self.world: self.world.drawGL()
        self.klamptwidgetmaster.drawGL(self.viewport())
    def display_screen(self):
        glDisable(GL_LIGHTING)
        glColor3f(0,0,0)
        h = 30
        """
        if self.instructions() != None:
            glRasterPos(20,h)
            gldraw.glutBitmapString(GLUT_BITMAP_HELVETICA_12,"Instructions: "+self.instructions())
            h += 20
        if self.description != None:
            glRasterPos(20,h)
            gldraw.glutBitmapString(GLUT_BITMAP_HELVETICA_12,"Description: "+self.description)
            h += 20
        glRasterPos(20,h)
        gldraw.glutBitmapString(GLUT_BITMAP_HELVETICA_12,"Press 'x' to exit without saving, 'q' to save+exit")
        """
    def viewport(self):
        return self.qtwidget.viewport()
    def idlesleep(self,seconds):
        self.qtwidget.idlesleep(seconds)
    def refresh(self):
        self.qtwidget.refresh()
    def click_ray(self,x,y):
        return self.qtwidget.click_ray(x,y)
    def initialize(self):
        return False
    def reshapefunc(self,w,h):
        self.width,self.height = w,h
        return False
    def keyboardfunc(self,c,x,y):
        self.klamptwidgetmaster.keypress(c)
        return False
    def keyboardupfunc(self,c,x,y):
        return False
    def specialfunc(self,c,x,y):
        self.klamptwidgetmaster.keypress(c)
        return False
    def specialupfunc(self,c,x,y):
        return False
    def mousefunc(self,button,state,x,y):
        if button == self.klamptwidgetbutton:
            if state == 0:  #down
                if self.klamptwidgetmaster.beginDrag(x,self.height-y,self.viewport()):
                    self.klamptwidgetdragging = True
            else:
                if self.klamptwidgetdragging:
                    self.klamptwidgetmaster.endDrag()
                self.klamptwidgetdragging = False
            if self.klamptwidgetmaster.wantsRedraw():
                self.refresh()
            return True
        return False
    def motionfunc(self,x,y,dx,dy):
        if self.klamptwidgetdragging:
            self.klamptwidgetmaster.drag(dx,-dy,self.viewport())
            if self.klamptwidgetmaster.wantsRedraw():
                self.refresh()
            return True
        else:
            self.klamptwidgetmaster.hover(x,self.height-y,self.viewport())
            if self.klamptwidgetmaster.wantsRedraw():
                self.refresh()
        return False
    def idlefunc(self):
        self.klamptwidgetmaster.idle()
        return True

class ConfigVisualEditor(VisualEditorBase):
    def __init__(self,name,value,description,world):
        VisualEditorBase.__init__(self,name,value,description,world)
        world.robot(0).setConfig(value)
        self.clicked = None
        self.hovered = None
        self.robotposer = RobotPoser(world.robot(0))
        self.addWidget(self.robotposer)
    
    def instructions(self):
        return 'Right-click and drag on the robot links to pose the robot'

    def mousefunc(self,button,state,x,y):
        if VisualEditorBase.mousefunc(self,button,state,x,y):
            self.value = self.robotposer.get()

    def display(self):
        #Override display handler since the widget draws the robot
        #the next few lines draw everything but the robot
        for i in xrange(self.world.numTerrains()):
            self.world.terrain(i).drawGL()
        for i in xrange(self.world.numRigidObjects()):
            self.world.rigidObject(i).drawGL()
        for i in xrange(1,self.world.numRobots()):
            self.world.robot(i).drawGL()
        #this line will draw the robot
        self.klamptwidgetmaster.drawGL(self.viewport())

class PointVisualEditor(VisualEditorBase):
    def __init__(self,name,value,description,world,frame=None):
        VisualEditorBase.__init__(self,name,value,description,world)
        self.frame = se3.identity() if frame==None else frame
        self.pointposer = PointPoser()
        self.pointposer.set(se3.apply(self.frame,value))
        self.pointposer.setFrame(self.frame[0])
        self.addWidget(self.pointposer)
    
    def instructions(self):
        return 'Right-click and drag on the widget to pose the point'

    def mousefunc(self,button,state,x,y):
        if VisualEditorBase.mousefunc(self,button,state,x,y):
            self.value = se3.apply(se3.inv(self.frame),self.pointposer.get())

class RotationVisualEditor(VisualEditorBase):
    def __init__(self,name,value,description,world,frame=None):
        VisualEditorBase.__init__(self,name,value,description,world)
        self.frame = se3.identity() if frame==None else frame
        self.xformposer = TransformPoser()
        self.xformposer.set(*se3.mul(self.frame,(value,[0,0,0])))
        self.xformposer.enableRotation(True)
        self.xformposer.enableTranslation(False)
        self.addWidget(self.xformposer)
    
    def instructions(self):
        return 'Right-click and drag on the widget to pose the rotation'

    def mousefunc(self,button,state,x,y):
        if VisualEditorBase.mousefunc(self,button,state,x,y):
            self.value = se3.mul(se3.inv(self.frame),self.xformposer.get())[0]

class RigidTransformVisualEditor(VisualEditorBase):
    def __init__(self,name,value,description,world,frame=None):
        VisualEditorBase.__init__(self,name,value,description,world)
        self.frame = se3.identity() if frame==None else frame
        self.xformposer = TransformPoser()
        self.xformposer.set(*se3.mul(self.frame,value))
        self.xformposer.enableRotation(True)
        self.xformposer.enableTranslation(True)
        self.addWidget(self.xformposer)
    
    def instructions(self):
        return 'Right-click and drag on the widget to pose the transform'

    def mousefunc(self,button,state,x,y):
        if VisualEditorBase.mousefunc(self,button,state,x,y):
            self.value = se3.mul(se3.inv(self.frame),self.xformposer.get())


class ObjectTransformVisualEditor(VisualEditorBase):
    def __init__(self,name,value,description,world,object):
        VisualEditorBase.__init__(self,name,value,description,world)
        self.object = object
        self.objposer = ObjectPoser(object)
        self.addWidget(self.objposer)
    
    def instructions(self):
        return 'Right-click and drag on the widget to pose the object'

    def mousefunc(self,button,state,x,y):
        if VisualEditorBase.mousefunc(self,button,state,x,y):
            self.value = self.objposer.get()



#Qt stuff
_app = None
_dialog = None
_glwidget = None

class AppGLWidget(qtprogram.GLNavigationProgram):
    def __init__(self):
        qtprogram.GLNavigationProgram.__init__(self,"GLWidget")
        self.iface = None
    def setInterface(self,iface):
        self.iface = iface
        if iface:
            iface.qtwidget = self
            iface.reshapefunc(self.width,self.height)
        self.refresh()
    def initialize(self):
        if self.iface: self.iface.initialize()
        qtprogram.GLNavigationProgram.initialize(self)
    def reshapefunc(self,w,h):
        if self.iface==None or not self.iface.reshapefunc(w,h):
            qtprogram.GLNavigationProgram.reshapefunc(self,w,h)
    def keyboardfunc(self,c,x,y):
        if self.iface==None or not self.iface.keyboardfunc(c,x,y):
            qtprogram.GLNavigationProgram.keyboardfunc(self,c,x,y)
    def keyboardupfunc(self,c,x,y):
        if self.iface==None or not self.iface.keyboardupfunc(c,x,y):
            qtprogram.GLNavigationProgram.keyboardupfunc(self,c,x,y)
    def specialfunc(self,c,x,y):
        if self.iface==None or not self.iface.specialfunc(c,x,y):
            qtprogram.GLNavigationProgram.specialfunc(self,c,x,y)
    def specialupfunc(self,c,x,y):
        if self.iface==None or not self.iface.specialupfunc(c,x,y):
            qtprogram.GLNavigationProgram.specialupfunc(self,c,x,y)
    def motionfunc(self,x,y,dx,dy):
        if self.iface==None or not self.iface.motionfunc(x,y,dx,dy):
            qtprogram.GLNavigationProgram.motionfunc(self,x,y,dx,dy)
    def mousefunc(self,button,state,x,y):
        if self.iface==None or not self.iface.mousefunc(button,state,x,y):
            qtprogram.GLNavigationProgram.mousefunc(self,button,state,x,y)
    def idlefunc(self):
        if self.iface!=None: self.iface.idlefunc()
        qtprogram.GLNavigationProgram.idlefunc(self)
    def display(self):
        if self.iface!=None:
            self.iface.display()
    def display_screen(self):
        if self.iface!=None:
            self.iface.display_screen()

class MyDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        global _glwidget
        _glwidget.initWindow(self)
        self.instructions = QLabel()
        self.description = QLabel()
        self.description2 = QLabel("Press OK to save, Cancel to continue without saving")
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.description)
        self.layout.addWidget(self.instructions)
        self.layout.addWidget(_glwidget)
        self.layout.addWidget(self.description2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,Qt.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)
    def setEditor(self,editorObject):
        self.editorObject = editorObject
        self.setWindowTitle("Editing "+editorObject.name)
        _glwidget.setInterface(editorObject)
        if editorObject.description==None:
            self.description.setText("")
        else:
            self.description.setText(editorObject.description)
        self.instructions.setText(editorObject.instructions())
    def finish(self):
        _glwidget.setInterface(None)
        res = self.editorObject.value
        self.editorObject = None
        return res

def _launch(editorObject):
    global _app,_dialog,_glwidget
    if _app == None:
        #Do Qt setup
        _app = QApplication(["Editor"])
        _glwidget = AppGLWidget()
        _dialog=MyDialog()
    _dialog.setEditor(editorObject)
    res = _dialog.exec_()
    retVal = _dialog.finish()
    return res,retVal

_editTemporaryWorlds = {}

def edit(name,value,type='auto',description=None,editor='visual',world=None,frame=None):
    """Launches an editor for the given value.  Returns a pair (save,result)
    where save indicates what the user wanted to do with the edited value
    and result is the edited value."""
    if name == None and type=='auto':
        raise RuntimeError("Cannot do an anonymous edit without the 'type' argument specified")
    if name == None:
        name = 'Anonymous'
    if type == 'auto':
        type = nameToType(name)
    if isinstance(world,str):
        #a single argument, e.g., a robot file
        global _editTemporaryWorlds
        if world not in _editTemporaryWorlds:
            _editTemporaryWorlds[world] = WorldModel()
            if not _editTemporaryWorlds[world].readFile(world):
                raise RuntimeError("Error loading world file "+world)
        world = _editTemporaryWorlds[world]    
    if value==None:
        if type == 'Config':
            if world==None:
                raise RuntimeError("Cannot visually edit a Config resource without a world")
            value = world.robot(0).getConfig()
        elif type == 'Configs':
            raise RuntimeError("Cannot visually edit a Configs resource without a world")
            value = [world.robot(0).getConfig()]
        elif type == 'IKGoal':
            value = IKObjective()
        elif type == 'Vector3' or type == 'Point':
            value = [0,0,0]
        elif type == 'Rotation':
            value = so3.identity()
        elif type == 'RigidTransform':
            value = se3.identity()
        else:
            raise RuntimeError("Don't know how to edit objects of type "+type)
    if type == 'Config':
        return _launch(ConfigVisualEditor(name,value,description,world))
    elif type == 'Configs':
        return _launch(ConfigsVisualEditor(name,value,description,world))
    elif type == 'Vector3' or type == 'Point':
        if isinstance(frame,(RigidObjectModel,RobotLink)):
            frame = frame.getTransform()
        return _launch(PointVisualEditor(name,value,description,world,frame))
    elif type == 'Rotation':
        if isinstance(frame,(RigidObjectModel,RobotLink)):
            frame = frame.getTransform()
        return _launch(RotationVisualEditor(name,value,description,world,frame))
    elif type == 'RigidTransform':
        if isinstance(frame,RigidObjectModel):
            return _launch(ObjectTransformVisualEditor(name,value,description,world,frame))
        return _launch(RigidTransformVisualEditor(name,value,description,world,frame))
    else:
        raise RuntimeError("Don't know how to edit objects of type "+type)
    
