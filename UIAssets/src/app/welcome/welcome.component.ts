import {Component, OnInit, OnDestroy, TemplateRef, ViewChild} from '@angular/core';
import {Router} from '@angular/router';
import {environment} from '../../environments/environment';
import {BackendService} from "../_service/backend.service";
import {PreferencesService} from "../_service/preferences.service";
import {Fabric, FabricList} from "../_model/fabric";
import {ModalService} from '../_service/modal.service';
import {concat, Observable, of, Subject} from "rxjs";
import {repeatWhen, retryWhen, tap, delay, takeUntil} from "rxjs/operators";
import {catchError, debounceTime, distinctUntilChanged, switchMap} from "rxjs/operators";
import {EndpointList, Endpoint} from '../_model/endpoint';
import {NgSelectComponent} from '@ng-select/ng-select';

@Component({
    selector: 'app-welcome',
    templateUrl: './welcome.component.html',
    styleUrls: ['./welcome.component.css']
})

export class WelcomeComponent implements OnInit, OnDestroy {
    app_mode = environment.app_mode;
    userRole: number = 0;
    rows = [];
    showFabricModal: boolean;
    fabrics: Fabric[];
    fabricName: string;
    managerRunning: boolean = true;
    loadingCount = 0;
    sorts = [{prop: 'fabric', dir: 'asc'}];
    @ViewChild('addFabric') addFabricModal: TemplateRef<any>;
    @ViewChild('endpointSearch') public ngSelect: NgSelectComponent;
    endpoints$: Observable<any>;
    endpointInput$ = new Subject<string>();
    endpointLoading: boolean = false;
    endpointList = [];
    endpointMatchCount: number = 0;
    endpointHeader: boolean = false;
    private onDestroy$ = new Subject<boolean>();

    constructor(public backendService: BackendService, private router: Router, private prefs: PreferencesService,
                public modalService: ModalService) {
        this.userRole = this.prefs.userRole;
        this.rows = [];
        this.fabrics = [];
        this.fabricName = '';
    }

    ngOnInit() {
        this.getFabrics();
        this.searchEndpoint();
        this.backgroundPollManagerStatus();
    }

    ngOnDestroy(): void {
        this.onDestroy$.next(true);
        this.onDestroy$.complete();
    }

    // sliently manager status at regular interval
    backgroundPollManagerStatus(){
        this.backendService.getAppManagerStatus().pipe(
            repeatWhen(delay(10000)),
            takeUntil(this.onDestroy$),
            retryWhen( error => error.pipe(
                tap(val => {
                    console.log("manager refresh error occurred");
                }),
                delay(1000)
            ))
        ).subscribe(
            (data) => {
                if("manager" in data && "status" in data["manager"] && data["manager"]["status"] == "running"){
                    this.managerRunning = true;
                } else {
                    this.managerRunning = false;
                }
            }
        );
    }

    getFabricStatus(fabric:Fabric){
        this.loadingCount++;
        this.backendService.getFabricStatus(fabric).subscribe(
            (data) => {
                this.loadingCount--;
                if("status" in data){
                    fabric.set_status(data['status'])
                }
                if("uptime" in data){
                    fabric.uptime = data["uptime"]
                }
            },
            (error) => {
                this.loadingCount--;
                this.modalService.setModalError({
                    "body": 'Failed to load fabric status for '+fabric.fabric+'. '+ error['error']['error']
                });
            }
        )
    }

    getFabricCount(fabric:Fabric, count_type:string){
        this.loadingCount++;
        this.backendService.getActiveMacAndIps(fabric, count_type).subscribe(
            (data) => {
                this.loadingCount--;
                if("count" in data){
                    fabric[count_type] = data["count"];
                }
            },
            (error) => {
                this.loadingCount--;
                this.modalService.setModalError({
                    "body": 'Failed to load fabric active count for '+fabric.fabric+'. '+ error['error']['error']
                });
            }
        )
    }

    getFabrics(sorts = this.sorts) {
        this.loadingCount = 1;
        this.backendService.getFabrics(sorts).subscribe(
            (data) => {
                let fabric_list = new FabricList(data);
                this.fabrics = [];
                this.rows = [];
                this.loadingCount--;
                for (const fabric of fabric_list.objects) {
                    this.fabrics.push(fabric);
                    this.rows.push(fabric);
                    this.getFabricStatus(fabric);
                    this.getFabricCount(fabric, "mac");
                    this.getFabricCount(fabric, "ipv4");
                    this.getFabricCount(fabric, "ipv6");
                }
            },
            (error) => {
                this.loadingCount = 0;
                this.modalService.setModalError({
                    "body": 'Failed to load fabrics. ' + error['error']['error']
                });
            }
        )
    }

    public showAddFabric(){
        this.modalService.openModal(this.addFabricModal)
    }

    public submitFabric(){
        this.modalService.hideModal();
        this.loadingCount++;
        this.backendService.createFabric(new Fabric({"fabric":this.fabricName})).subscribe(
            (data) => {
                this.loadingCount--;
                this.router.navigate(['/fabric', this.fabricName, 'settings', 'connectivity']);
            },
            (error) => {
                this.loadingCount--;
                this.modalService.setModalError({
                    "body": 'Failed to create fabric. ' + error['error']['error']
                })
            }
        );
    }

    public onEndPointChange(endpoint) {
        this.endpointList = [];
        this.endpointMatchCount = 0;
        this.endpointHeader = false;
        if(endpoint && "vnid" in endpoint && endpoint.vnid>0){
            this.ngSelect.clearModel();
            this.router.navigate(['/fabric', endpoint.fabric, 'history', endpoint.vnid, endpoint.addr]);
        } else if (typeof(endpoint)!=="undefined"){  
            this.ngSelect.clearModel();
        }
    }

    private searchEndpoint() {
        this.endpoints$ = concat(
            of([]), // default items
            this.endpointInput$.pipe(
                debounceTime(200),
                distinctUntilChanged(),
                tap(() => {
                    this.endpointLoading = true;
                    this.endpointMatchCount = 0;
                    this.endpointList = [];
                }),
                switchMap(term => this.backendService.searchEndpoint(term).pipe(
                    catchError(() => of([])), // empty list on error
                    tap(() => {
                        this.endpointLoading = false;
                    })
                ))
            )
        );
        this.endpoints$.subscribe(
            (data) => {
                if("objects" in data){
                    let endpoint_list = new EndpointList(data);
                    this.endpointList = endpoint_list.objects;
                    this.endpointMatchCount = endpoint_list.count;
                    this.endpointHeader = true;
                    if(this.endpointList.length==0){
                        //dummy result to hide 'not found' error on valid search (we have match count=0 already displayed)
                        this.endpointList = [new Endpoint()]
                    }
                } else {
                    //search was not performed
                    this.endpointList = [];
                    this.endpointMatchCount = 0;
                    this.endpointHeader = false;
                }          
            }
        );
    }
}
