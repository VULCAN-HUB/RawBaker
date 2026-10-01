"""Session-local selection history, separate from project edit history."""
from copy import deepcopy


class SelectionHistory:
    def __init__(self,limit=50):
        self.limit=limit;self.reset()

    def reset(self):
        self.current=(None,False);self.past=[];self.future=[]

    def change(self,points=None,inverted=False):
        value=(deepcopy(points),bool(inverted))
        if value==self.current:return False
        self.past.append(deepcopy(self.current));self.past=self.past[-self.limit:]
        self.future.clear();self.current=value;return True

    def undo(self):
        if not self.past:return False
        self.future.append(deepcopy(self.current));self.current=self.past.pop();return True

    def redo(self):
        if not self.future:return False
        self.past.append(deepcopy(self.current));self.current=self.future.pop();return True
