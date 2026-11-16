import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const ledger={months:()=>api('/ledger/months'),month:m=>api('/ledger/months/'+m),ingest:(m,data)=>api('/ledger/months/'+m+'/ingest',{method:'POST',body:JSON.stringify(data)}),createOrder:m=>api('/ledger/months/'+m+'/publish-orders',{method:'POST',body:'{}'}),publish:id=>api('/ledger/publish-orders/'+id+'/publish',{method:'POST',body:'{}'})};
