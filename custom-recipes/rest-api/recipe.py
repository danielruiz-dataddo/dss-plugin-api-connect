# -*- coding: utf-8 -*-
import dataiku
from dataiku.customrecipe import get_input_names_for_role, get_recipe_config, get_output_names_for_role
from dataikuapi.utils import DataikuException
from rest_api_client import RestAPIClient
import pandas as pd
import copy
from safe_logger import SafeLogger
from dku_utils import get_dku_key_values

logger = SafeLogger("rest-api plugin", forbiden_keys=["token", "password"])


def is_error_message(jsons_response):
    if "error" in jsons_response and len(jsons_response) == 1:
        return True
    else:
        return False


input_A_names = get_input_names_for_role('input_A_role')
config = get_recipe_config()
dku_flow_variables = dataiku.get_flow_variables()

logger.info("config={}".format(logger.filter_secrets(config)))

credential = config.get("credential", {})
endpoint = config.get("endpoint", {})
extraction_key = endpoint.get("extraction_key", "")
raw_output = endpoint.get("raw_output", None)
parameter_columns = config.get("parameter_columns", [])
if len(parameter_columns) == 0:
    raise ValueError("There is no parameter column selected.")
parameter_renamings = get_dku_key_values(config.get("parameter_renamings", {}))

column_to_parameter = {}
for parameter_column in parameter_columns:
    if parameter_column in parameter_renamings:
        column_to_parameter[parameter_column] = parameter_renamings[parameter_column]
    else:
        column_to_parameter[parameter_column] = parameter_column
custom_key_values = get_dku_key_values(config.get("custom_key_values", {}))
id_list = dataiku.Dataset(input_A_names[0])
partitioning = id_list.get_config().get("partitioning")
if partitioning:
    dimensions_types = partitioning.get("dimensions", [])
    dimensions = []
    for dimension_type in dimensions_types:
        dimensions.append(dimension_type.get("name"))
    for dimension in dimensions:
        dimension_src = "DKU_DST_{}".format(dimension)
        if dimension_src in dku_flow_variables:
            custom_key_values[dimension] = dku_flow_variables.get(dimension_src)
id_list_df = id_list.get_dataframe()
results = []
time_last_request = None

for index, row in id_list_df.iterrows():
    updated_endpoint = copy.deepcopy(endpoint)
    base_output_row = {}
    if column_to_parameter == {}:
        for key, value in row._asdict().items():
            updated_endpoint.update({key: value})
    else:
        for column_name in column_to_parameter:
            parameter_name = column_to_parameter[column_name]
            updated_endpoint.update({parameter_name: row[column_name]})
            base_output_row.update({parameter_name: row[column_name]})
    logger.info("Creating client with credential={}, updated_endpoint={}".format(logger.filter_secrets(credential), updated_endpoint))
    client = RestAPIClient(credential, updated_endpoint, custom_key_values=custom_key_values)
    client.time_last_request = time_last_request
    while client.has_more_data():
        json_response = client.paginated_get(can_raise_exeption=False)
        if extraction_key == "":
            # Todo: check api_response key is free and add something overwise
            if is_error_message(json_response):
                base_output_row.update(json_response)
            else:
                base_output_row.update({"api_response": json_response})
            results.append(base_output_row)
        else:
            data = json_response.get(extraction_key, [json_response])
            if data is None:
                raise DataikuException("Extraction key '{}' was not found in the incoming data".format(extraction_key))
            for result in data:
                if raw_output:
                    if is_error_message(result):
                        base_output_row.update(result)
                    else:
                        base_output_row.update({"api_response": result})
                else:
                    base_output_row.update(result)
                results.append(base_output_row)
    time_last_request = client.time_last_request

output_names_stats = get_output_names_for_role('api_output')
odf = pd.DataFrame(results)

if odf.size > 0:
    api_output = dataiku.Dataset(output_names_stats[0])
    api_output.write_with_schema(odf)
