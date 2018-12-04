import { Component, OnInit, ViewChild, TemplateRef } from '@angular/core';
import { BackendService } from '../../../_service/backend.service';
import { PreferencesService } from '../../../_service/preferences.service';
import { ModalService } from '../../../_service/modal.service';

@Component({
  selector: 'app-cleared',
  templateUrl: './cleared.component.html',
})
export class ClearedComponent implements OnInit {

  endpoint:any ;
  rows:any ;
  loading=true;
  pageSize = 25 ;
  sorts = [{ prop:'events[0].ts' , dir:'desc'}] ;
  @ViewChild('errorMsg') msgModal : TemplateRef<any> ;
  constructor(private backendService:BackendService, private prefs: PreferencesService, public modalService:ModalService) { 
    this.endpoint = this.prefs.selectedEndpoint ;
    this.rows = [] ;
    
  }

  ngOnInit() {
    if (this.endpoint.events.length === 0) {
      this.getClearedEndpoints(this.endpoint.fabric,this.endpoint.first_learn.node, this.endpoint.vnid, this.endpoint.addr);
  } else {
    this.getClearedEndpoints(this.endpoint.fabric,this.endpoint.events[0].node, this.endpoint.vnid, this.endpoint.addr);
  }
      
  }

  getClearedEndpoints(fabricName,node,vnid,address) {
    this.loading = true ;
    this.backendService.getClearedEndpoints(fabricName,node,vnid,address).subscribe(
      (data) => {
        debugger ;
          this.rows = [];
          for (let object of data.objects) {
              const endpoint = object["ept.remediate"];
              this.rows.push(endpoint);
          }
          this.loading = false;
      },
      (error) => {
          this.loading = false;
          const msg = 'Failed to load cleared endpoints! ' + error['error']['error'] ;
          this.modalService.setAndOpenModal('error','Error',msg,this.msgModal) ;
      }
  )
  }

}
