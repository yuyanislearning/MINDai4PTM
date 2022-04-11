import json
import pdb
import numpy as np
from sklearn.metrics import average_precision_score
from sklearn import metrics
from sklearn.metrics import precision_recall_curve

from pprint import pprint

ptm2ptm = {'O-linked_glycosylation':'glyco_ST', 'S-palmitoyl_cysteine':'Palm_C','Hydroxyproline':'Hydro_P',\
    'Pyrrolidone_carboxylic_acid':'Pyro_Q','Phosphoserine':'Phos_ST', 'Hydroxylysine':'Hydro_K',\
    'Ubiquitination':'Ubi_K','Methyllysine':'Methy_K','N6-acetyllysine':'N6-ace_K',\
    'SUMOylation':'SUMO_K','Methylarginine':'Methy_R','Phosphotyrosine':'Phos_Y',\
    'N-linked_glycosylation':'glyco_N','Phosphothreonine':'Phos_ST'}

label2aa = {'Hydro_K':'K','Hydro_P':'P','Methy_K':'K','Methy_R':'R','N6-ace_K':'K','Palm_C':'C',
        'Phos_ST':'ST','Phos_Y':'Y','Pyro_Q':'Q','SUMO_K':'K','Ubi_K':'K','glyco_N':'N','glyco_ST':'ST'}

y_preds = {}
AUPRs = {}
AUCs = {}
precisions = {}
recalls = {}
f1s = {}
MCCs = {}

with open('/workspace/PTM/Data/Musite_data/PTM_test/PTMTrans_predict_15fold_random_avg.json') as f:
    predict_dat = json.load(f)

with open('/workspace/PTM/Data/Musite_data/ptm/PTM_test.json') as f:
    dat = json.load(f)

for sptm in predict_dat:
    uid = sptm.split('_')[0]
    site = int(sptm.split('_')[1])
    ptm_type = sptm.split('_')[2]+'_'+sptm.split('_')[3]
    if y_preds.get(uid,-1)==-1:
        y_preds[uid] = [(site, ptm_type, predict_dat[sptm])]
    else:
        y_preds[uid].append((site, ptm_type, predict_dat[sptm]))

for ptm in label2aa.keys():#['Hydro_K', 'Hydro_P', 'Methy_K', 'Methy_R']:
    y_trues = []
    predictions = []
    for k in dat:
        y_pred = y_preds[k]
        pos_l = []
        pred_prob = []
        P_exist = False
        for pred in y_pred:
            if pred[1]==ptm:
                pos_l.append(pred[0])
                pred_prob.append(float(pred[2]))
        pos_l = np.array(pos_l)
        pred_prob = np.array(pred_prob)
        y_true = np.zeros(pos_l.shape)
        for lbl in dat[k]['label']:
            if lbl['ptm_type']==ptm:
                P_exist=True# exist true label in this prot
                y_true[np.where(pos_l==int(lbl['site']))[0]] = 1 # plus one to match the indexing, create true labels
        if P_exist:# if no positive labels, not count in it bc no evidence of PTM exists or not
            y_trues.append(y_true)
            predictions.append(pred_prob)
    y_trues = np.concatenate(y_trues, axis=0)
    predictions = np.concatenate(predictions, axis = 0)
    pred_label = np.zeros(predictions.shape)
    pred_label[np.where(predictions>0.5)] = 1

    fpr, tpr, thresholds = metrics.roc_curve(y_trues, predictions)
    precision, recall, thresholds = precision_recall_curve(y_trues, predictions)
    # pdb.set_trace()

    AUPRs[ptm] = average_precision_score(y_trues, predictions)
    AUCs[ptm] = metrics.auc(fpr, tpr)
    precisions[ptm] = metrics.precision_score(y_trues, pred_label)
    recalls[ptm] = metrics.recall_score(y_trues, pred_label)
    f1s[ptm] = metrics.f1_score(y_trues, pred_label)
    MCCs[ptm] = metrics.matthews_corrcoef(y_trues, pred_label)

for ptm in label2aa.keys():
    print(ptm)
print('AUPR')
for ptm in label2aa.keys():
    print('%.3f'%(AUPRs[ptm]))

print('AUC')
for ptm in label2aa.keys():
    print('%.3f'%(AUCs[ptm]))

print('precision')
for ptm in label2aa.keys():
    print('%.3f'%(precisions[ptm]))

print('recall')
for ptm in label2aa.keys():
    print('%.3f'%(recalls[ptm]))

print('f1')
for ptm in label2aa.keys():
    print('%.3f'%(f1s[ptm]))

print('MCC')
for ptm in label2aa.keys():
    print('%.3f'%(MCCs[ptm]))
