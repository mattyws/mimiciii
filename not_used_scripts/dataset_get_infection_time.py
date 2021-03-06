"""
Get the suspicion of infection time for each icustay
The suspicion of infection is given by:
    If antibiotics is prescribed first, a culture have to be taken in 72h
    If the culture is first, a antibiotic have to be administered in 24h
The events from prescription and microbiologyevents considered are the ones thar occur IN the icustay (between intime
and outtime), because MIMIC don't have events charted out of the icu context, which reflects into the inability
to calculate the SOFA score outside the icustay.
Antibiotic and routes names came from https://github.com/alistairewj/sepsis3-mimic/blob/master/query/tbls/abx-poe-list.sql
"""
from datetime import timedelta
from functools import partial

import numpy
import pandas as pd
import multiprocessing as mp
import sys

from resources import functions

pd.set_option('mode.chained_assignment', None)

def get_infection_time(icustays, prescriptions, microbiologyevents, parameters, manager_queue=None):
    antibiotics_names = [
        'adoxa', 'ala-tet', 'alodox', 'amikacin', 'amikin', 'amoxicillin', 'clavulanate',
        'ampicillin', 'augmentin', 'avelox', 'avidoxy', 'azactam', 'azithromycin', 'aztreonam', 'axetil', 'bactocill',
        'bactrim', 'bethkis', 'biaxin', 'bicillin l-a', 'cayston', 'cefazolin', 'cedax', 'cefoxitin', 'ceftazidime',
        'cefaclor', 'cefadroxil', 'cefdinir', 'cefditoren', 'cefepime', 'cefotetan', 'cefotaxime', 'cefpodoxime',
        'cefprozil', 'ceftibuten', 'ceftin', 'cefuroxime ', 'cefuroxime', 'cephalexin', 'chloramphenicol', 'cipro',
        'ciprofloxacin', 'claforan', 'clarithromycin', 'cleocin', 'clindamycin', 'cubicin', 'dicloxacillin', 'doryx',
        'doxycycline', 'duricef', 'dynacin', 'ery-tab', 'eryped', 'eryc', 'erythrocin', 'erythromycin', 'factive',
        'flagyl', 'fortaz', 'furadantin', 'garamycin', 'gentamicin', 'kanamycin', 'keflex', 'ketek', 'levaquin',
        'levofloxacin', 'lincocin', 'macrobid', 'macrodantin', 'maxipime', 'mefoxin', 'metronidazole', 'minocin',
        'minocycline', 'monodox', 'monurol', 'morgidox', 'moxatag', 'moxifloxacin', 'myrac', 'nafcillin sodium',
        'nicazel doxy 30', 'nitrofurantoin', 'noroxin', 'ocudox', 'ofloxacin', 'omnicef', 'oracea', 'oraxyl',
        'oxacillin', 'pc pen vk', 'pce dispertab', 'panixine', 'pediazole', 'penicillin', 'periostat', 'pfizerpen',
        'piperacillin', 'tazobactam', 'primsol', 'proquin', 'raniclor', 'rifadin', 'rifampin', 'rocephin', 'smz-tmp',
        'septra', 'septra ds', 'septra', 'solodyn', 'spectracef', 'streptomycin sulfate', 'sulfadiazine',
        'sulfamethoxazole', 'trimethoprim', 'sulfatrim', 'sulfisoxazole', 'suprax', 'synercid', 'tazicef',
        'tetracycline',
        'timentin', 'tobi', 'tobramycin', 'trimethoprim', 'unasyn', 'vancocin', 'vancomycin', 'vantin', 'vibativ',
        'vibra-tabs', 'vibramycin', 'zinacef', 'zithromax', 'zmax', 'zosyn', 'zyvox'
    ]
    icustays_for_infection = []
    for index, icustay in icustays.iterrows():
        icu_prescriptions = prescriptions[prescriptions['HADM_ID'] == icustay['hadm_id']]
        icu_prescriptions.loc[:, 'DRUG'] = icu_prescriptions.loc[:, 'DRUG']\
            .map(lambda x: x.lower() if not pd.isna(x) else x)
        # Get the antibiotics prescriptions for this icu
        icu_prescriptions = icu_prescriptions[
            (icu_prescriptions['DRUG'].isin(antibiotics_names))
            | (
                (icu_prescriptions['DRUG'].str.startswith('amoxicillin'))
                & (icu_prescriptions['DRUG'].str.endswith('clavulanate'))
            )
            & (icu_prescriptions['DRUG_TYPE'].isin(['MAIN', 'ADDITIVE']))
            ]
        # Now remove the antibiotics based on the route of administration
        icu_prescriptions = icu_prescriptions[
            ~(icu_prescriptions['ROUTE'].isin(['OU', 'OS', 'OD', 'AU', 'AS', 'AD', 'TP']))
            & ~(icu_prescriptions['ROUTE'].str.contains('eye'))
            & ~(icu_prescriptions['ROUTE'].str.contains('ear'))
            & ~(icu_prescriptions['ROUTE'].str.contains('cream'))
            & ~(icu_prescriptions['ROUTE'].str.contains('desensitization'))
            & ~(icu_prescriptions['ROUTE'].str.contains('ophth oint'))
            & ~(icu_prescriptions['ROUTE'].str.contains('gel'))
            ]
        icu_prescriptions.loc[:, 'STARTDATE'] = pd.to_datetime(icu_prescriptions['STARTDATE'],
                                                               format=parameters['date_pattern'])
        icu_prescriptions = icu_prescriptions.sort_values(by=['STARTDATE'])
        # print(icu_prescriptions[['HADM_ID', 'DRUG', 'ROUTE', 'ICUSTAY_ID', 'STARTDATE', 'ENDDATE']])
        icu_microbiologyevents = microbiologyevents[
            # (microbiologyevents['CHARTTIME'] >= icustay['intime'])
            # & (microbiologyevents['CHARTTIME'] <= icustay['outtime'])
            # &
             (icustay['hadm_id'] == microbiologyevents['HADM_ID'])
            ]
        icu_microbiologyevents.loc[:, 'CHARTTIME'] = pd.to_datetime(icu_microbiologyevents['CHARTTIME'],
                                                                    format=parameters['datetime_pattern'])
        icu_microbiologyevents = icu_microbiologyevents.sort_values(by=['CHARTTIME'])
        # print(icu_microbiologyevents[['HADM_ID', 'CHARTTIME', 'ORG_NAME']])
        icustay = icustay.loc[['hadm_id', 'icustay_id', 'intime', 'outtime', 'gender', 'ethnicity',
                               'age', 'dbsource']]
        infection_time = None
        for index2, prescription in icu_prescriptions.iterrows():
            before_prescription = prescription['STARTDATE'] - timedelta(hours=24)
            aux_microbiologyevents = icu_microbiologyevents[
                (icu_microbiologyevents['CHARTTIME'] <= before_prescription)
            ]
            if len(aux_microbiologyevents) != 0:
                infection_time = aux_microbiologyevents.iloc[0]['CHARTTIME']
                break
            after_prescription = prescription['STARTDATE'] + timedelta(hours=72)
            aux_microbiologyevents = icu_microbiologyevents[
                (icu_microbiologyevents['CHARTTIME'] >= after_prescription)
            ]
            if len(aux_microbiologyevents) != 0:
                infection_time = prescription['STARTDATE']
                break
        icustay['suspected_infection_time_poe'] = infection_time
        icustay['suspicion_poe'] = True if infection_time is not None else None
        icustays_for_infection.append(icustay)
        if manager_queue is not None:
            manager_queue.put(index)
    icustays_for_infection = pd.DataFrame(icustays_for_infection)
    return icustays_for_infection

parameters = functions.load_parameters_file()
# For now, load all the prescriptions and microbiologyevents csv into memory (they are small, but may be changed in
# future)
print("Loading prescriptions")
prescriptions = pd.read_csv(parameters['mimic_data_path'] + parameters['csv_files_directory'] + 'PRESCRIPTIONS.csv')
print("Loading microbiologyevents")
microbiologyevents = pd.read_csv(parameters['mimic_data_path'] + parameters['csv_files_directory']
                                 + 'MICROBIOLOGYEVENTS.csv')
print("Loading icustays")
icustays = pd.read_csv('sepsis3-df-no-exclusions.csv')
total_files = len(icustays)
with mp.Pool(processes=6) as pool:
    m = mp.Manager()
    queue = m.Queue()
    partial_get_infection_time = partial(get_infection_time, prescriptions=prescriptions,
                                      microbiologyevents=microbiologyevents, parameters=parameters, manager_queue=queue)
    icustays_split = numpy.array_split(icustays, 200)
    map_obj = pool.map_async(partial_get_infection_time, icustays_split)
    consumed = 0
    while not map_obj.ready():
        for _ in range(queue.qsize()):
            queue.get()
            consumed += 1
        sys.stderr.write('\rdone {0:%}'.format(consumed / total_files))
    print()
    icustays_for_infection = map_obj.get()
    icustays_for_infection = pd.concat(icustays_for_infection, ignore_index=True)
    for column in icustays_for_infection.columns:
        if column.lower() != column:
            icustays_for_infection[column.lower()] = icustays_for_infection[column]
            icustays_for_infection = icustays_for_infection.drop(columns=[column])
    icustays_for_infection.loc[:, 'suspected_infection_time_poe'] = pd.to_datetime(
        icustays_for_infection['suspected_infection_time_poe'], format=parameters['datetime_pattern'])
    print("Total infected patients {}".format(len(icustays_for_infection[icustays_for_infection['suspicion_poe'] == True])))
    icustays_for_infection.to_csv('sepsis3_df_no_exclusions.csv', index=False)
