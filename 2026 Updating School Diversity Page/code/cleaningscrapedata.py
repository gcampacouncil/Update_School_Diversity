import pandas as pd
import numpy as np
import re
from datetime import datetime
import matplotlib.pyplot as plt
import csv 

hs_data = pd.read_csv('/Users/GCampa/Desktop/Updating School Diversity Page/mydata/hs_school_data.csv')
hst_data = pd.read_csv('/Users/GCampa/Desktop/Updating School Diversity Page/mydata/hst_school_data.csv')
d75_data = pd.read_csv('/Users/GCampa/Desktop/Updating School Diversity Page/mydata/d75_school_data.csv')

hs_hstdata = pd.concat([hs_data, hst_data], ignore_index=True)
all_hsdata = pd.concat([hs_hstdata, d75_data], ignore_index=True)

schools = pd.read_excel('/Users/GCampa/Desktop/Updating School Diversity Page/origdata/demographic-snapshot-2021-22-to-2025-26-public.xlsx', sheet_name='School')
schools25 = schools[schools['Year'] == '2024-25'].copy()
hsgrades = (
    (schools25['Grade 9'] > 0)
    | (schools25['Grade 10'] > 0)
    | (schools25['Grade 11'] > 0)
    | (schools25['Grade 12'] > 0)
)
hs25 = schools25[hsgrades].copy()

hs25['dbn'] = hs25['DBN']
merged_hsdata = pd.merge(all_hsdata, hs25, on='dbn', how='left')

merged_hsdata.to_csv('/Users/GCampa/Desktop/Updating School Diversity Page/mydata/hsdata_full.csv', index=False)
#print(merged_1)

#merged_2 = pd.merge(merged_1,amen_bpl_orig, on='NAME', how='left')
#print(merged_2)

#merged_3 = pd.merge(merged_2,amen_nypl_orig, on='NAME', how='left')
#print(merged_3)
