import ast
import copy
import requests
import hpc.autoscale.hpclogging as log
from collections import namedtuple
from requests_cache import CachedSession

#import logging

# This is just for working around CC api
HPC_SKU = "Standard_F2s_v2"
HPC_CORE_COUNT = 2
HTC_SKU = "Standard_F2s_v2"
HTC_CORE_COUNT = 2
class azurecost:
    def __init__(self, config: dict):

        self.config = config
        self.retail_url = "https://prices.azure.com/api/retail/prices?api-version=2021-10-01-preview&meterRegion='primary'"
        self.clusters = config['cluster_name']
        self.dimensions = namedtuple("dimensions", "cost,usage,region,meterid,meter,metercat,metersubcat,resourcegroup,tags,currency")
        acm_name = f"{config['cache_root']}/cost"
        retail_name = f"{config['cache_root']}/retail"
        self.retail_session = CachedSession(cache_name=retail_name,
                                            backend='filesystem',
                                            allowable_codes=(200,),
                                            allowable_methods=('GET'),
                                            expire_after=172800)

        #_az_logger = logging.getLogger('azure.identity')
        #_az_logger.setLevel(logging.ERROR)
        ## If we have ACM data available use azcost format else use retail format.
        ## for nodearray, combine usage data with either azcost or retail format.
        self.DEFAULT_AZCOST_FORMAT="sku_name,region,spot,meter,meterid,metercat,metersubcat,resourcegroup,rate,currency"
        self.RETAIL_FORMAT="sku_name,region,spot,meter,meterid,metercat,rate,currency"
        self.NODEARRAY_USAGE_FORMAT="nodearray,core_hours"

    def do_meter_lookup(self, sku_name, spot, region):
        """
        check cache storage if we have seen this meter's rate
        before
        """
        return None

    def check_cost_avail(self, start, end):
        """
        For a given time period, check if we have
        cost data available.
        """
        return False

    def get_azcost_job(self, sku_name, region, spot):

        fmt = []

        if not self.do_meter_lookup(sku_name, region, spot):
            # We do not have a rate for this meter id, get info from retail.
            fmt = self.RETAIL_FORMAT.split(',')
            az_fmt_t = namedtuple('az_fmt_t', fmt)
            data = self.get_retail_rate(sku_name, region, spot)
            az_fmt = az_fmt_t(sku_name=sku_name, region=region,spot=spot,meter=data['meterName'],
                                meterid=data['meterId'],metercat=data['serviceName'],
                                rate=data['retailPrice'], currency=data['currencyCode'])
            return az_fmt
        else:
            pass


    def get_azcost_nodearray(self, start, end):

        fmt = []

        if not self.check_cost_avail(start, end):
            # we do not have cost data available, use retail format.
            fmt = (self.RETAIL_FORMAT + self.NODEARRAY_USAGE_FORMAT).split(',')
            az_fmt_t = namedtuple('az_fmt_t', fmt)
        return


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
        return self.config

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

    def get_usage(self, clustername: str, start: str, end: str, granularity: str):

        endpoint = f"{self.config['url']}/clusters/{clustername}/usage"
        params = {}
        params['granularity'] = granularity
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

        #This is a temporary hack to work around CC api for now.
        for e in usage['usage'][0]['breakdown']:
            if e['category'] == 'nodearray':
                if e['node'] == 'hpc':
                    use = e['hours']
                    if 'details' not in e:
                        e['details'] = []
                    a = {}
                    a['vm_size'] = hpc
                    a['hours'] = use
                    a['core_count'] = hpc_cores
                    a['region'] = 'eastus'
                    a['priority'] = 'regular'
                    a['os'] = 'linux'
                    e['details'].append(a)
                elif e['node'] == 'htc':
                    use = e['hours']
                    if 'details' not in e:
                        e['details'] = []
                    a = {}
                    a['vm_size'] = htc
                    a['hours'] = use
                    a['core_count'] = htc_cores
                    a['region'] = 'eastus'
                    a['priority'] = 'spot'
                    a['os'] = 'linux'
                    e['details'].append(a)

        return usage
