import { Component, OnInit, ViewChild, TemplateRef } from '@angular/core';
import { BackendService } from '../../../_service/backend.service';
import { PreferencesService } from '../../../_service/preferences.service';
import { ModalService } from '../../../_service/modal.service';

@Component({
  selector: 'app-rapid',
  templateUrl: './rapid.component.html',
})
export class RapidComponent implements OnInit {


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
      this.getRapidEndpoints(this.endpoint.fabric, this.endpoint.vnid, this.endpoint.addr);
  }

  getRapidEndpoints(fabricName,vnid,address) {
    this.loading = true ;
    this.backendService.getRapidEndpoints(fabricName,vnid,address).subscribe(
      (data) => {
          this.rows = [];
          for (let object of data.objects) {
              const endpoint = object["ept.rapid"];
              this.rows.push(endpoint);
          }
          this.loading = false;
      },
      (error) => {
          this.loading = false;
          const msg = 'Failed to load rapid endpoints! ' + error['error']['error'] ;
          this.modalService.setAndOpenModal('error','Error',msg,this.msgModal) ;
      }
    )
  }

}
