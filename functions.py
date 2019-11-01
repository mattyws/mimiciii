import html
import json
import os
import pickle
import sys
from datetime import datetime, timedelta
import time
import re
from itertools import islice
from xml.sax.saxutils import escape, quoteattr

import nltk
import pandas as pd

from os.path import exists, join, abspath
from os import pathsep

import unicodedata

from nltk import WhitespaceTokenizer
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, cohen_kappa_score, accuracy_score, \
    confusion_matrix, classification_report

DATE_PATTERN = "%Y-%m-%d"
DATETIME_PATTERN = "%Y-%m-%d %H:%M:%S"


def load_parameters_file():
    if not os.path.exists('parameters.json'):
        raise FileNotFoundError("Parameter file doesn't exists!")
    parameters = json.load(open('parameters.json'))
    return parameters

def chunk_lst(data, SIZE=10000):
    it = iter(data)
    for i in range(0, len(data), SIZE):
        yield [k for k in islice(it, SIZE)]


def filter_events_before_infection(events, admittime, infection_time, preceding_time,
                                   datetime_pattern=DATETIME_PATTERN, time_key="charttime"):
    """
    Get events that occur from admission time until infection time minus preceding time
    :param events: the events
    :param admittime: the admission time
    :param infection_time: the infection time
    :param preceding_time: the preceding time to get the events
    :param datetime_pattern: the pattern used to store time
    :param key: the dictionary key that has the event time
    :return: 
    """
    admittime_datetime = datetime.strptime(admittime, datetime_pattern)
    infection_datetime = datetime.strptime(infection_time, datetime_pattern) - timedelta(hours=preceding_time)
    new_events = []
    for event in events:
        # Pega a data do evento e o transforma em datetime
        event_datetime = datetime.strptime(event[time_key], datetime_pattern)
        # Compara se o evento aconteceu entre a data de adimissão e a data de infecção (já alterada)
        if event_datetime > admittime_datetime and event_datetime <= infection_datetime:
            new_events.append(event)
    return new_events



def filter_since_time(events_object, time_str, max_interval, datetime_pattern=DATETIME_PATTERN, key="charttime", after=False):
    time_point = time.strptime(time_str, datetime_pattern)
    filtered_objects = []
    for event in events_object:
        if len(event[key]) > 0:
            event_date = time.strptime(event[key], datetime_pattern)
            if after:
                difference = (time.mktime(event_date) - time.mktime(time_point)) / 3600
            else:
                difference = (time.mktime(time_point) - time.mktime(event_date)) / 3600
            if difference >= 0 and difference <= max_interval:
                filtered_objects.append(event)
    return filtered_objects




def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]


def search_file(filename, search_path):
    """Given a search path, find file
    """
    file_path = None
    for path in search_path:
        if exists(join(path, filename)):
            file_path = path
            break
    if file_path:
        return abspath(join(file_path, filename))
    return None

def get_file_path_from_id(id, search_paths):
    file_path = search_file('{}.json'.format(id), search_paths)
    return file_path

def get_files_by_ids(ids, search_paths):
    """
    Get the path to the json files from a list of ids
    :param ids: the ids to search for file
    :param search_paths: the paths where the json files are listed
    :return: a dictionary of id : path to json file or None in case of no file found
    """
    files_paths = dict()
    for id in ids:
        path = get_file_path_from_id(id, search_paths)
        files_paths[id] = path
    return files_paths


def chartevents_is_error(event):
    return (pd.notnull(event['ERROR']) and event['ERROR'] != 0) \
           or (pd.notnull(event['STOPPED']) and event['STOPPED'] != 'NotStopd')
           # or (pd.isnull(event['ERROR']) and pd.isnull(event['STOPPED']))

def noteevents_is_error(event):
    return event['ISERROR'] == 1

def is_noteevent_category(event, categories):
    categories = [x.lower() for x in categories]
    if event['CATEGORY'].lower() in categories:
        return True
    return False


def event_is_error(event_label, event, noteevent_category_to_delete=None):
    """
    Check if the event passed as parameter is an error
    :param event_label: the table from where this event is
    :param event: a pandas.Series or similar representing the event
    :return: True if is a error, false otherwise
    """
    if event_label == 'CHARTEVENTS':
        return chartevents_is_error(event)
    elif event_label == 'LABEVENTS':
        # Labevents has no error label
        return False
    elif event_label == 'NOTEEVENTS':
        is_category_to_delete = False
        if noteevent_category_to_delete is not None:
            is_category_to_delete = is_noteevent_category(event, noteevent_category_to_delete)
        return noteevents_is_error(event) or is_category_to_delete
    else:
        raise NotImplemented("Handling error for this table is not implemented yet, exiting.")


def get_event_itemid_and_value(event_label, event):
    """
    Get the value and its id based from which table the event is.
    :param event_label: the table from where this event is
    :param event: a pandas.Series or similar representing the event
    :return:
    """
    if event_label == 'NOTEEVENTS':
        itemid = "Note"
        event_value = event['TEXT']
    elif event_label == 'CHARTEVENTS' or event_label == 'LABEVENTS':
        # Get values and store into a variable, just to read easy and if the labels change
        itemid = event['ITEMID']
        # print(event['VALUE'], event['VALUENUM'])
        if pd.isnull(event['VALUENUM']):
            event_value = str(event['VALUE'])
        else:
            event_value = float(event['VALUENUM'])
    else:
        raise NotImplemented("Event label don't have a filter for its value and itemid!")
    return itemid, event_value


def divide_by_events_lenght(data_list, classes, sizes_filename="sizes.pkl", classes_filename="sizes_labels.pkl"):
    """
    Divide a dataset based on their number of timesteps
    :param data_list: list of data
    :param classes: labels for these data
    :param sizes_filename: filename used to save the final sizes object
    :param classes_filename: filename to save the final labels object
    :return:
    """
    sizes = None
    labels = None
    if os.path.exists(sizes_filename):
        with open(sizes_filename, 'rb') as sizes_handler:
            sizes = pickle.load(sizes_handler)
    if os.path.exists(classes_filename):
        with open(classes_filename, 'rb') as sizes_handler:
            labels = pickle.load(sizes_handler)
    if sizes is None and labels is None:
        sizes = dict()
        labels = dict()
        aux = 0
        for d, c in zip(data_list, classes):
            sys.stderr.write('\rdone {0:%}'.format(aux / len(data_list)))
            aux += 1
            with open(d, 'rb') as file_handler:
                try:
                    values = pickle.load(file_handler)
                except Exception as e:
                    print(d)
                    print("test")
                    print(e)
                    raise ValueError()
                if len(values) not in sizes.keys():
                    sizes[len(values)] = []
                    labels[len(values)] = []
                sizes[len(values)].append(d)
                labels[len(values)].append(c)
        with open(sizes_filename, 'wb') as sizes_handler:
            pickle.dump(sizes, sizes_handler)
        with open(classes_filename, 'wb') as sizes_handler:
            pickle.dump(labels, sizes_handler)
    return sizes, labels


def load_ctakes_parameters_file():
    if not os.path.exists('ctakes_parameters.json'):
        raise FileNotFoundError("cTakes parameter file doesn't exists!")
    parameters = json.load(open('ctakes_parameters.json'))
    return parameters


def remove_only_special_characters_tokens(tokens):
    new_tokens = []
    for token in tokens:
        if not re.match(r'^[\W_]+$', token):
            new_tokens.append(token)
    return new_tokens


def test_model(kerasAdapter, dataTestGenerator, fold):
    testClasses, result = kerasAdapter.predict_generator(dataTestGenerator)
    metrics = dict()
    metrics['fscore'] = f1_score(testClasses, result, average='weighted')
    metrics['precision'] = precision_score(testClasses, result, average='weighted')
    metrics['recall'] = recall_score(testClasses, result, average='weighted')
    metrics['auc'] = roc_auc_score(testClasses, result, average='weighted')

    metrics['fscore_b'] = f1_score(testClasses, result)
    metrics['precision_b'] = precision_score(testClasses, result)
    metrics['recall_b'] = recall_score(testClasses, result)
    metrics['auc_b'] = roc_auc_score(testClasses, result)

    metrics['kappa'] = cohen_kappa_score(testClasses, result)
    metrics['accuracy'] = accuracy_score(testClasses, result)
    tn, fp, fn, metrics['tp_rate'] = confusion_matrix(testClasses, result).ravel()
    print(classification_report(testClasses, result))
    metrics["fold"] = fold
    return metrics

def print_with_time(text):
    print("{} ===== {} =====".format(datetime.now().strftime("%d/%m %H:%M:%S"), text))

def escape_invalid_xml_characters(text):
    text = escape(text)
    text = quoteattr(text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return text


def escape_html_special_entities(text):
    return html.unescape(text)


def text_to_lower(text):
    return text.lower()

def whitespace_tokenize_text(text):
    tokenizer = WhitespaceTokenizer()
    return tokenizer.tokenize(text)

def tokenize_text(text):
    sentence_detector = nltk.data.load('tokenizers/punkt/english.pickle')
    return sentence_detector.tokenize(text)


def tokenize_sentences(sentences):
    tokenized_sentences = []
    for sentence in sentences:
        tokenized_sentences.append(whitespace_tokenize_text(sentence))
    return tokenized_sentences