#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 28 09:37:26 2019

@author: weetee
"""
import os
import math
import torch
import torch.nn as nn
from ..misc import save_as_pickle, load_pickle
from seqeval.metrics import precision_score, recall_score, f1_score
import logging
from tqdm import tqdm

logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', \
                    datefmt='%m/%d/%Y %I:%M:%S %p', level=logging.INFO)
logger = logging.getLogger(__file__)

def load_state(net, optimizer, scheduler, args, load_best=False):
    """ Loads saved model and optimizer states if exists """
    base_path = "./data/"
    amp_checkpoint = None
    checkpoint_path = os.path.join(base_path,"task_test_checkpoint_%d.pth.tar" % args.model_no)
    best_path = os.path.join(base_path,"task_test_model_best_%d.pth.tar" % args.model_no)
    start_epoch, best_pred, checkpoint = 0, 0, None
    if (load_best == True) and os.path.isfile(best_path):
        checkpoint = torch.load(best_path)
        logger.info("Loaded best model.")
    elif os.path.isfile(checkpoint_path):
        checkpoint = torch.load(checkpoint_path)
        logger.info("Loaded checkpoint model.")
    if checkpoint != None:
        start_epoch = checkpoint['epoch']
        best_pred = checkpoint['best_acc']
        net.load_state_dict(checkpoint['state_dict'])
        if optimizer is not None:
            optimizer.load_state_dict(checkpoint['optimizer'])
        if scheduler is not None:
            scheduler.load_state_dict(checkpoint['scheduler'])
        amp_checkpoint = checkpoint['amp']
        logger.info("Loaded model and optimizer.")    
    return start_epoch, best_pred, amp_checkpoint

def load_results(model_no=0):
    """ Loads saved results if exists """
    losses_path = "./data/task_test_losses_per_epoch_%d.pkl" % model_no
    accuracy_path = "./data/task_train_accuracy_per_epoch_%d.pkl" % model_no
    f1_path = "./data/task_test_f1_per_epoch_%d.pkl" % model_no

    f1_micro_path = "./data/task_test_f1_nonseq_micro_per_epoch_%d.pkl" % model_no
    f1_macro_path = "./data/task_test_f1_nonseq_macro_per_epoch_%d.pkl" % model_no
    test_accuracy_path = "./data/task_test_accuracy_per_epoch_%d.pkl" % model_no
    precision_recall_micro_path = "./data/task_test_precision_recall_micro_per_epoch_%d.pkl" % model_no
    precision_recall_macro_path = "./data/task_test_precision_recall_macro_per_epoch_%d.pkl" % model_no
    report_path = "./data/task_report_per_epoch_%d.pkl" % model_no

    if os.path.isfile(losses_path) and os.path.isfile(accuracy_path) and os.path.isfile(f1_path) \
        and os.path.isfile(f1_micro_path) and os.path.isfile(f1_macro_path) and os.path.isfile(test_accuracy_path):

        losses_per_epoch = load_pickle("task_test_losses_per_epoch_%d.pkl" % model_no)
        accuracy_per_epoch = load_pickle("task_train_accuracy_per_epoch_%d.pkl" % model_no)
        f1_per_epoch = load_pickle("task_test_f1_per_epoch_%d.pkl" % model_no)

        f1_micro_per_epoch = load_pickle("task_test_f1_per_epoch_%d.pkl" % model_no)
        f1_macro_per_epoch = load_pickle("task_test_f1_per_epoch_%d.pkl" % model_no)
        test_accuracy_per_epoch = load_pickle("task_test_f1_per_epoch_%d.pkl" % model_no)

        precision_recall_micro_per_epoch = load_pickle("task_test_precision_recall_micro_per_epoch_%d.pkl" % model_no)
        precision_recall_macro_per_epoch = load_pickle("task_test_precision_recall_macro_per_epoch_%d.pkl" % model_no)

        report_per_epoch = load_pickle("task_report_per_epoch_%d.pkl" % model_no)

        logger.info("Loaded results buffer")
    else:
        losses_per_epoch, accuracy_per_epoch, f1_per_epoch, f1_micro_per_epoch, \
        f1_macro_per_epoch, test_accuracy_per_epoch, precision_recall_micro_per_epoch, \
        precision_recall_macro_per_epoch, report_per_epoch = [], [], [], [], [], [], [], [], []
    return losses_per_epoch, accuracy_per_epoch, f1_per_epoch, f1_micro_per_epoch, \
        f1_macro_per_epoch, test_accuracy_per_epoch, precision_recall_micro_per_epoch, \
        precision_recall_macro_per_epoch, report_per_epoch


def evaluate_(output, labels, ignore_idx):
    ### ignore index 0 (padding) when calculating accuracy
    idxs = (labels != ignore_idx).squeeze()
    o_labels = torch.softmax(output, dim=1).max(1)[1]
    l = labels.squeeze()[idxs]; o = o_labels[idxs]

    try:
        if len(idxs) > 1:
            acc = (l == o).sum().item()/len(idxs)
        else:
            acc = (l == o).sum().item()
    except TypeError: # len() of a 0-d tensor
        acc = (l == o).sum().item()
        
    l = l.cpu().numpy().tolist() if l.is_cuda else l.numpy().tolist()
    o = o.cpu().numpy().tolist() if o.is_cuda else o.numpy().tolist()

    return acc, (o, l)


def convert_cr_idx2rel(cr):
    rm = load_pickle("relations.pkl")
    new_cr = {}
    general_metrics = ['accuracy', 'macro avg', 'weighted avg']
    for gm in general_metrics:
        new_cr[gm] = cr[gm]

    for k, v in cr.items():
        if not k in general_metrics:
            new_cr[rm.idx2rel[int(k)].replace('\n', '')] = cr[k]
    
    return cr


from sklearn.metrics import precision_recall_fscore_support, accuracy_score, classification_report
def evaluate_results(net, test_loader, pad_id, cuda):
    logger.info("Evaluating test samples...")
    acc = 0; out_labels = []; true_labels = []
    net.eval()
    with torch.no_grad():
        for i, data in tqdm(enumerate(test_loader), total=len(test_loader)):
            x, e1_e2_start, labels, _,_,_ = data
            attention_mask = (x != pad_id).float()
            token_type_ids = torch.zeros((x.shape[0], x.shape[1])).long()

            if cuda:
                x = x.cuda()
                labels = labels.cuda()
                attention_mask = attention_mask.cuda()
                token_type_ids = token_type_ids.cuda()
                
            classification_logits = net(x, token_type_ids=token_type_ids, attention_mask=attention_mask, Q=None,\
                          e1_e2_start=e1_e2_start)
            
            accuracy, (o, l) = evaluate_(classification_logits, labels, ignore_idx=-1)
            out_labels.append([str(i) for i in o]); true_labels.append([str(i) for i in l])
            acc += accuracy
    
    accuracy = acc/(i + 1)
    results = {
        "accuracy": accuracy,
        "precision": precision_score(true_labels, out_labels),
        "recall": recall_score(true_labels, out_labels),
        "f1": f1_score(true_labels, out_labels)
    }

    # converting relation specific metrics from ids to labels
    cr = convert_cr_idx2rel(classification_report(
        y_true=[tl for batch in true_labels for tl in batch],
        y_pred=[pl for batch in out_labels for pl in batch],
        output_dict=True
    ))
    test_accuracy = cr['accuracy']

    results_non_seq_macro = {
        "precision":  cr['macro avg']['precision'],
        "recall": cr['macro avg']['recall'],
        "f1": cr['macro avg']['f1-score']
    }

    p_micro, r_micro, f_micro, _ = precision_recall_fscore_support(
        y_true=[tl for batch in true_labels for tl in batch],
        y_pred=[pl for batch in out_labels for pl in batch],
        average='micro',
        zero_division=0
    )

    results_non_seq_micro = {
        "precision": p_micro,
        "recall": r_micro,
        "f1": f_micro
    }



    test_accuracy = accuracy_score(
        y_true=[tl for batch in true_labels for tl in batch],
        y_pred=[pl for batch in out_labels for pl in batch],
    )

    logger.info("***** Eval results *****")
    for key in sorted(results.keys()):
        # logger.info("  %s = %s", key, str(results[key]))
        if key != 'accuracy':
            logger.info(f'test {key}(micro, macro) = ({results_non_seq_micro[key]:.3f},{results_non_seq_macro[key]:.3f})')
        else:
            logger.info(f'{key} (training) = {results[key]:.3f}')

    return results, results_non_seq_micro, results_non_seq_macro, test_accuracy, cr
    