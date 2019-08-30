"""
Remove features that have a low frequency of occurrence in patients.
"""

import os
import pickle
import pprint

import sys

import functions
import pandas as pd
import numpy as np

pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 3)

parameters = functions.load_parameters_file()
pp = pprint.PrettyPrinter(indent=4)

dataset = pd.read_csv(parameters['mimic_data_path'] + parameters['insight_dataset_file_name'])
patient_events_path = parameters['mimic_data_path'] + "sepsis_separated_features/"

features_frequency = dict()
i = 0
print("====== Getting frequencies =====")
for icustay in dataset['icustay_id']:
    sys.stderr.write('\rdone {0:%}'.format(i / len(dataset)))
    if not os.path.exists(patient_events_path + "{}.csv".format(icustay)):
        continue
    events = pd.read_csv(patient_events_path + "{}.csv".format(icustay))
    for feature in events.columns:
        if feature not in features_frequency.keys():
            features_frequency[feature] = 0
        features_frequency[feature] += 1
    i += 1

features_to_remove = set()
for feature in features_frequency.keys():
    if features_frequency[feature] / len(dataset) < 0.20:
        features_to_remove.add(feature)


i = 0
new_events_path = parameters['mimic_data_path'] + parameters['features_low_frequency_removed_dirname']
if not os.path.exists(new_events_path):
    os.mkdir(new_events_path)

print("====== Removing low frequency features =====")
for icustay in dataset['icustay_id']:
    sys.stderr.write('\rdone {0:%}'.format(i / len(dataset)))
    if not os.path.exists(patient_events_path + "{}.csv".format(icustay)):
        continue
    events = pd.read_csv(patient_events_path + "{}.csv".format(icustay))
    features_in_patient = set(events.columns)
    features_to_remove_from_patient = list(features_to_remove.intersection(features_in_patient))
    events = events.drop(columns=features_to_remove_from_patient)
    events = events.sort_index(axis=1)
    events.to_csv()
    i += 1