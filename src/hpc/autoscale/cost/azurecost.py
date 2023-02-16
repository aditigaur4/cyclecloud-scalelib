import ast
import copy
import requests
import hpc.autoscale.hpclogging as log
from collections import namedtuple
from requests_cache import CachedSession

import logging

class azurecost:
    def __init__(self, config: dict):

        self.config = config
        self.base_url = "https://management.azure.com"
        self.subscription = config['accounting']['subscription_id']
        self.scope = f"subscriptions/{self.subscription}"
        self.query_url = f"https://management.azure.com/{self.scope}/providers/Microsoft.CostManagement/query?api-version=2021-10-01"
        self.retail_url = "https://prices.azure.com/api/retail/prices?api-version=2021-10-01-preview&meterRegion='primary'"
        self.clusters = config['cluster_name']
        self.dimensions = namedtuple("dimensions", "cost,usage,region,meterid,meter,metercat,metersubcat,resourcegroup,tags,currency")
        acm_name = f"{config['cache_root']}/cost"
        self.acm_session = CachedSession(cache_name=acm_name,
                                    backend='filesystem',
                                    allowable_methods=('GET','POST'),
                                    ignored_parameters=['Authorization'])
        retail_name = f"{config['cache_root']}/retail"
        self.retail_session = CachedSession(cache_name=retail_name,
                                            backend='filesystem',
                                            allowable_codes=(200,),
                                            allowable_methods=('GET'),
                                            expire_after=172800)

        _az_logger = logging.getLogger('azure.identity')
        _az_logger.setLevel(logging.ERROR)

    def get_retail_rate(self, armskuname: str, armregionname: str, spot: bool):

        params = {}
        filters = f"armRegionName eq '{armregionname}' and armSkuName eq '{armskuname}' and serviceName eq 'Virtual Machines'"
        params['$filter'] = filters

        res = self.retail_session.get(self.retail_url, params=params)
        if res.status_code != 200:
            log.error(f"{res.json()}")
            raise res.raise_for_status()
        data = res.json()
        
        for e in data['Items']:
            if e['type'] != 'Consumption':
                continue

            if e['productName'].__contains__("Windows"):
                continue

            if e['meterName'].__contains__("Low Priority"):
                continue

            if spot:
                if e['meterName'].__contains__("Spot"):
                    return e

            return e
    
    def test_azure_cost(self):

        log.info("Test azure cost")
        return self.config,self.acm_session

    def get_info_from_retail(self, meterId: str):

        sku = 'armSkuName'
        region = 'armRegionName'
        filters = f"meterId eq '{meterId}'"
        params = {}
        params['$filter'] = filters

        res = self.retail_session.get(self.retail_url, params=params)
        if res.status_code != 200:
            log.error(f"{res.json()}")
            raise res.raise_for_status()
        
        data = res.json()
        sku_list = []
        for e in data['Items']:
            if e[sku] and e[region]:
                sku_list.append((e[sku],e[region]))
        return sku_list

    def get_usage(self, clustername: str, start: str, end: str):

        endpoint = f"{self.config['url']}/clusters/{clustername}/usage"
        params = {}
        params['granularity'] = 'total'
        params['timeframe'] = 'custom'
        params['from'] = start
        params['to'] = end
        uname = self.config['username']
        pw = self.config['password']
        res = requests.get(url=endpoint, params=params, auth=(uname,pw), verify=False)
        if res.status_code != 200:
            log.error(res.reason)
            res.raise_for_status()

        usage = copy.deepcopy(res.json())

        hpc = 'Standard_F2s_v2'
        hpc_cores = 2
        htc = 'Standard_F2s_v2'
        htc_cores = 2
        #This is a temporary hack to work around CC api for now.
        for e in usage['usage'][0]['breakdown']:
            if e['category'] == 'nodearray':
                if e['node'] == 'hpc':
                    use = e['hours']
                    if 'vm_sizes' not in e:
                        e['vm_sizes'] = {}
                    e['vm_sizes'][hpc] = {}
                    e['vm_sizes'][hpc]['core_hours'] = use
                    e['vm_sizes'][hpc]['core_count'] = hpc_cores
                    e['vm_sizes'][hpc]['region'] = 'eastus'
                elif e['node'] == 'htc':
                    use = e['hours']
                    if 'vm_sizes' not in e:
                        e['vm_sizes'] = {}
                    e['vm_sizes'][htc] = {}
                    e['vm_sizes'][htc]['core_hours'] = use
                    e['vm_sizes'][htc]['core_count'] = htc_cores
                    e['vm_sizes'][htc]['region'] = 'eastus'

        return usage


