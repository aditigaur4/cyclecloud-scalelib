import ast
import hpc.autoscale.hpclogging as log
from collections import namedtuple
from requests_cache import CachedSession
import warnings
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