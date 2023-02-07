import hpc.autoscale.hpclogging as log
from collections import namedtuple
from requests_cache import CachedSession
from jinja2 import Environment, FileSystemLoader
import warnings
import logging
with warnings.catch_warnings():
    warnings.filterwarnings("ignore")
    from azure.identity import DefaultAzureCredential
    from azure.core.exceptions import ClientAuthenticationError

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
                                    ignored_parameters=['Authorization'],
                                    expire_after=3600)
        retail_name = f"{config['cache_root']}/retail"
        self.retail_session = CachedSession(cache_name=retail_name,
                                            backend='filesystem',
                                            allowable_codes=(200,),
                                            allowable_methods=('GET'),
                                            expire_after=3600)

        _az_logger = logging.getLogger('azure.identity')
        _az_logger.setLevel(logging.ERROR)

    def test_azure_cost(self):

        log.info("Test azure cost")
        return self.config,self.acm_session
    def get_tokens(self):

        token_url = self.base_url + "/.default"
        try:
            cred = DefaultAzureCredential()
            access_token = cred.get_token(token_url)
        except ClientAuthenticationError as e:
            log.error(e.message)
            raise
        return access_token

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
        #log.debug(f"Total retail records: {data['Count']}")
        sku_list = []
        for e in data['Items']:
            if e[sku] and e[region]:
                sku_list.append((e[sku],e[region]))
        return sku_list
    
    def get_query_dataset(self, start: str, end: str):

        env = Environment(loader=FileSystemLoader("."))
        template = env.get_template("query.j2")
        query = template.render(clusters=self.clusters,
                                start_time=start,
                                end_time=end)
        return ast.literal_eval(query)

    def _process_response(self, data):
        
        def parse_clusername_tags(tags):
            clusters = []
            for row in tags:
                k,v = row.split(":", maxsplit=1)
                k = k.replace('"','')
                if k == "clustername":
                    clusters.append(v.replace('"',''))
            return clusters
    
        prices = {}
        for row in map(self.dimensions._make, data['properties']['rows']):
            if row.metercat != "Virtual Machines":
                continue
            meterId = row.meterid
            clusters = parse_clusername_tags(row.tags)
            meter_price = (row.cost / row.usage) * 3
            for (sku_name,region) in self.get_info_from_retail(meterId):
                if not sku_name:
                    continue

                if region not in prices:
                    prices[region] = {}
                if sku_name in prices[region]:
                    continue

                prices[region][sku_name] = cost_fmt.pricing(meter=row.meter,meterid=row.meterid,
                                                metercat=row.metercat,metersubcat=row.metersubcat,
                                                resourcegroup=row.resourcegroup,
                                                rate=meter_price,cost=row.cost,
                                                currency=row.currency)
    
        return prices


    def getQueryUsage(self):

        start = self.config.az_start
        end = self.config.az_end
        access_token = self.get_tokens()
        query_dataset = self.get_query_dataset(start, end)
        headers = {'Authorization' : f'Bearer {access_token.token}'}
        parameter = {'scope': f'{self.scope}'}
        response = self.acm_session.post(self.query_url,
                                    headers=headers, params=parameter,
                                    json=query_dataset)
        log.debug(f"Using Cache: {response.from_cache}")
        if response.status_code == 429:
            log.error(f"status returned: {response.status_code}")
            log.error(f"{response.json()}")
            log.error(response.headers)
            raise response.raise_for_status()
        elif response.status_code != 200:
            log.error(f"{response.json()}")
            raise response.raise_for_status()
        return self._process_response(response.json())