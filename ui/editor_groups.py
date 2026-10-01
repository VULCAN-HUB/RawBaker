"""Folder rows for contiguous pass-through groups in the editor layer panel."""

from ui.editor_i18n import localize
from PyQt5.QtCore import Qt,QItemSelectionModel

from PyQt5.QtWidgets import QListWidgetItem,QInputDialog

from ui.studio_style import tool_icon

from core.layer_groups import make_group,change_group,set_clipping,ancestors,members



PREFIX='group:'





class EditorGroups:

    def group_rows(self,selected_headers=()):

        doc=self.project.state['documents'].get(self.document_id,{})

        groups=doc.get('groups',{});seen=set();self.layers.blockSignals(True)

        collapsed=getattr(self,'collapsed_groups',set());self.collapsed_groups=collapsed

        index=0

        while index<self.layers.count():

            item=self.layers.item(index);key=item.data(Qt.UserRole)

            layer=next((l for l in doc.get('layers',[]) if l.get('id')==key),None)

            if layer:

                chain=list(reversed(ancestors(doc,layer.get('group_id'))));item.setData(Qt.UserRole+1,layer.get('group_id'))

                item.setText('    '*len(chain)+(localize('클립 · ', self) if layer.get('clipped') else '')+layer['name'])

                for depth,group in enumerate(chain):

                    if group in seen:continue

                    seen.add(group);info=groups[group]

                    header=QListWidgetItem('    '*depth+('+ ' if group in collapsed else '− ')+info['name']+(localize(' · 잠금', self) if info['locked'] else ''))

                    header.setIcon(tool_icon('folder'));header.setData(Qt.UserRole,PREFIX+group)

                    header.setCheckState(Qt.Checked if info['visible'] else Qt.Unchecked)

                    header.setToolTip(localize('그룹 선택: 함께 이동/복제/삭제 · 두 번 클릭: 접기/펼치기', self))

                    self.layers.insertItem(index,header);index+=1

                    if group in selected_headers:

                        header.setSelected(True);self.layers.setCurrentItem(header,QItemSelectionModel.NoUpdate)

                if any(g in selected_headers for g in chain):item.setSelected(False)

            index+=1

        self.layers.blockSignals(False)

        self.filter_group_rows(self.layer_search.text())



    def filter_group_rows(self,text):

        text=text.casefold();doc=self.project.state['documents'].get(self.document_id,{})

        matches={g for l in doc.get('layers',[]) if text in l.get('name','').casefold() for g in ancestors(doc,l.get('group_id'))}

        groups=doc.get('groups',{});collapsed=getattr(self,'collapsed_groups',set())

        for i in range(self.layers.count()):

            item=self.layers.item(i);key=item.data(Qt.UserRole)

            if isinstance(key,str) and key.startswith(PREFIX):

                group=key[len(PREFIX):];parents=ancestors(doc,group)[1:]

                item.setHidden((not text and any(g in collapsed for g in parents)) or (bool(text) and group not in matches and not any(text in groups[g]['name'].casefold() for g in [group]+parents)))

            else:

                chain=ancestors(doc,item.data(Qt.UserRole+1))

                item.setHidden((not text and any(g in collapsed for g in chain)) or (text not in item.text().casefold() and not any(text in groups[g]['name'].casefold() for g in chain)))



    def current_group(self):

        item=self.layers.currentItem();key=item.data(Qt.UserRole) if item else None

        if isinstance(key,str) and key.startswith(PREFIX):return key[len(PREFIX):]

        layer=self.current_layer();return layer.get('group_id') if layer else None



    def select_group_header(self,group):

        for i in range(self.layers.count()):

            if self.layers.item(i).data(Qt.UserRole)==PREFIX+group:self.layers.setCurrentRow(i);return



    def create_layer_group(self):

        try:

            doc=self.project.state['documents'].get(self.document_id)

            if not doc:return

            key=make_group(self.project,self.document_id,self.selected_layer_ids(),localize('그룹 ', self)+str(len(doc.get('groups',{}))+1))

            self.refresh();self.select_group_header(key)

        except ValueError as error:self.error(error)



    def ungroup_layers(self):

        key=self.current_group()

        if key:

            try:change_group(self.project,self.document_id,key,ungroup=True);self.refresh()

            except ValueError as error:self.error(error)



    def rename_layer_group(self):

        key=self.current_group()

        if not key:return

        name,ok=QInputDialog.getText(self,localize('그룹 이름', self),localize('이름', self),text=self.project.state['documents'][self.document_id]['groups'][key]['name'])

        if ok:self.update_group(key,{'name':name})



    def update_group(self,key,values):

        try:change_group(self.project,self.document_id,key,values);self.refresh()

        except ValueError as error:self.error(error);self.refresh()



    def toggle_group_lock(self):

        key=self.current_group()

        if key:self.update_group(key,{'locked':not self.project.state['documents'][self.document_id]['groups'][key]['locked']})



    def toggle_clipping(self):

        layer=self.current_layer()

        if not layer or len(self.selected_layer_ids())!=1:

            self.status.setText(localize('클리핑할 레이어 하나를 선택하세요.', self));return

        try:set_clipping(self.project,self.document_id,layer['id'],not layer.get('clipped',False));self.refresh()

        except ValueError as error:self.error(error)



    def layer_double_clicked(self,item):

        key=item.data(Qt.UserRole)

        if isinstance(key,str) and key.startswith(PREFIX):

            group=key[len(PREFIX):]

            if group in self.collapsed_groups:self.collapsed_groups.remove(group)

            else:self.collapsed_groups.add(group)

            self.refresh();self.select_group_header(group)

        elif self.current_layer() and self.current_layer()['mask']:self.activate_tool('mask_brush')



    def relocate_layer(self,source,target,position):

        from core.layer_groups import relocate_block

        try:

            if relocate_block(self.project,self.document_id,source,target,position):

                if source.startswith(PREFIX):

                    doc=self.project.state['documents'][self.document_id]

                    self.collapsed_groups.difference_update(ancestors(doc,source[len(PREFIX):])[1:])

                    self.refresh();self.select_group_header(source[len(PREFIX):])

                else:

                    doc=self.project.state['documents'][self.document_id]

                    moved=next(l for l in doc['layers'] if l['id']==source)

                    self.collapsed_groups.difference_update(ancestors(doc,moved.get('group_id')))

                    self.pending_layer_selection=[source];self.layer_id=source;self.refresh()

                if self.layers.currentItem():self.layers.scrollToItem(self.layers.currentItem())

                self.status.setText(localize('레이어 이동 완료 · Ctrl+Z로 실행 취소', self))

        except ValueError as error:self.status.setText(localize(str(error), self))

