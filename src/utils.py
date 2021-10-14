from absl import flags
from absl import logging
import tensorflow as tf
import pandas as pd
from sklearn.metrics import f1_score, precision_recall_curve, auc, roc_auc_score, accuracy_score, confusion_matrix



import numpy as np
import random
import sys
import pdb
try:
    import ujson as json
except:
    import json
from Bio import SeqIO

from .tokenization import additional_token_to_index, n_tokens, tokenize_seq, parse_seq, aa_to_token_index, index_to_token



def handle_flags():
    flags.DEFINE_string("tflog",
            '3', "The setting for TF_CPP_MIN_LOG_LEVEL (default: 3)")
    flags.DEFINE_string('model',
            'rnn', 'model to use (default: proteinbert)')
    # Data configuration.
    flags.DEFINE_string('config',
            'config.yml', 'configure file (default: config.yml)')

    # Model parameters.
    flags.DEFINE_bool("multilabel", True, "multilabel or not (default: True)")
    flags.DEFINE_bool("binary", False, "Binary or not (default: True)")
    flags.DEFINE_bool("spec_neg_sam", True, "use ptm-specific negative sampling or not (default: True)")
    flags.DEFINE_bool("class_weights", False, "use class weights or not (default: True)")
    flags.DEFINE_bool("graph", False, "use only partial sequence (default: True)")


    # Training parameters.
    flags.DEFINE_integer("seq_len", 512, "maximum lenth+2 of the model sequence (default: 512)")
    flags.DEFINE_integer("batch_size", 256, "Batch Size (default: 32)")
    flags.DEFINE_integer("num_epochs",
            20, "Number of training epochs (default: 20)")
    flags.DEFINE_integer('random_seed',
            252, 'Random seeds for reproducibility (default: 252)')
    flags.DEFINE_float('learning_rate',
            1e-4, 'Learning rate while training (default: 1e-3)')
    flags.DEFINE_float('l2_reg',
            1e-3, 'L2 regularization lambda (default: 1e-3)')
    FLAGS = flags.FLAGS


def limit_gpu_memory_growth():
    gpus = tf.config.experimental.list_physical_devices('GPU')
    if gpus:
        # Restrict TensorFlow to only use the first GPU
        try:
            tf.config.experimental.set_visible_devices(gpus[0], 'GPU')
            tf.config.experimental.set_memory_growth(gpus[0], True)
            logical_gpus = tf.config.experimental.list_logical_devices('GPU')
            print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPU")
        except RuntimeError as e:
            # Visible devices must be set before GPUs have been initialized
          print(e)
          return False
    return True



class Data:
    def __init__(self, file_name, FLAGS):
        self.records = []
        # ptm_list = ['Phos_ST','Phos_Y','glyco_N','glyco_ST','Ubi_K','SUMO_K','N6-ace_K','Methy_R','Methy_K','Pyro_Q','Palm_C','Hydro_P','Hydro_K']
        # convert_ptm = {p:i+1 for i, p in enumerate(ptm_list)}
        # flatten = lambda l: [item for sublist in l for item in sublist]
        with open(file_name, 'r') as fp:
            # data structure: {PID:{seq, label:[{site, ptm_type}]}}
            dat = json.load(fp)
            for k in dat:
                # some case that the data miss sequence, skip
                if dat[k].get('seq',-1)==-1:
                    continue
                sequence = str(dat[k]['seq'])
                labels = dat[k]['label']
                self.records.append({
                    'uid': k,
                    'seq': sequence,
                    'label':labels
                })
        logging.info('Loaded {} records from {}.'.format(len(self.records),
            file_name))
        self.label2aa = {'Hydro_K':'K','Hydro_P':'P','Methy_K':'K','Methy_R':'R','N6-ace_K':'K','Palm_C':'C',
        'Phos_ST':'ST','Phos_Y':'Y','Pyro_Q':'Q','SUMO_K':'K','Ubi_K':'K','glyco_N':'N','glyco_ST':'ST'}
    def encode_data( self, seq_len,  unique_labels, class_weights=None, negative_sampling=False,is_binary=True, is_multilabel=False, spec_neg_sam=True, proteinbert=True, evaluate=False, train_val_test=None, graph=False):
        # only train on the protein with Alpha_fold prot
        dir = '/workspace/PTM/Data/Musite_data/Structure/AF_pro_'
        pro_list = []
        for line in open(dir+train_val_test+'.txt'):
            pro_list.append(line.strip())

        self.filter_records = [self.records[i] for i, r in enumerate(self.records) if len(r['seq'])<=(seq_len-2)]
        
        # get data
        data_seq = [d['seq'] for d in self.filter_records]
        data_label = [ d['label'] for d in self.filter_records]
        data_uid = [d['uid'] for d in self.filter_records]
        # filter on the protein with graph
        data_seq = [data_seq[i] for i in range(len(data_seq)) if data_uid[i] in pro_list]
        data_label = [data_label[i] for i in range(len(data_label)) if data_uid[i] in pro_list]
        data_uid = [uid for uid in data_uid if uid in pro_list]
        self.uid = data_uid

        if is_multilabel:# TODO add binary
            label_to_index = {str(label): i for i, label in enumerate(unique_labels)}
            Y = np.zeros((len(data_seq), seq_len, len(unique_labels))) 
            sample_weights = np.zeros((len(data_seq), seq_len, len(unique_labels)))

            for i, seq in enumerate(data_seq):
                # pos_ind = []
                for lbl in data_label[i]:
                    # for random case that site greater than seq
                    # if int(lbl['site']) > len(data_seq):
                    #     continue
                    Y[i, int(lbl['site'])+1, label_to_index[lbl['ptm_type']]] = 1 # add one since start padding 
                    sample_weights[i, int(lbl['site'])+1, label_to_index[lbl['ptm_type']]] =1
                    # pos_ind.append((int(lbl['site']),label_to_index[lbl['ptm_type']]))
                    # assert np.sum(sample_weights-Y)==0
                    
                if evaluate:
                    for u in unique_labels:
                        aa = self.label2aa[u]
                        neg_index = np.array([j for j,amino in enumerate(seq) if amino in aa])
                        if len(neg_index)<1:
                            continue
                        sample_weights[i, neg_index+1, label_to_index[u]] = 1
                    # for evaluation, get all negative sample

                # elif negative_sampling:
                #     sam_ind = np.array(choices([i for i in range(len(data_seq))],  k = len(pos_ind)*10)).astype(int)
                #     lbl_ind = np.array(choices([i for i in range(len(unique_labels))],  k=len(pos_ind)*10)).astype(int)
                #     count = 0
                #     for sa, lb in zip(sam_ind, lbl_ind):
                #         if (sa,lb) in pos_ind:
                #             continue
                #         sample_weights[i, sa+1, lb] = 1
                #         count+=1
                #         if count >= len(pos_ind):
                #             break
                # else:
                #     sample_weights[i, 1:(1+len(data_seq)), :] = 1
            Y = Y.reshape((len(data_seq),-1, 1))
            if class_weights is None:
                class_weights = np.repeat([1], len(unique_labels))
            if not evaluate:
                sample_weights = np.tile(class_weights, (len(data_seq), seq_len, 1)) * sample_weights
            sample_weights = sample_weights.reshape((len(data_seq), -1, 1))
            # assert np.sum(sample_weights-Y)==0

        self.Y  = Y
        self.sample_weights = sample_weights
        
        
        # Encode X 

        # if graph:
        #     if not is_binary:
        #         if proteinbert:
        #             X = [tokenize_seqs(data_seq, seq_len), np.zeros((len(data_seq), 8943)), adjs]
        #         else:
        #             X = [tokenize_seqs(data_seq, seq_len), adjs]
        # else:
        if not is_binary:
            X = [tokenize_seqs(data_seq, seq_len), np.zeros((len(data_seq), 8943))] if proteinbert else \
                [tokenize_seqs(data_seq, seq_len)]
        self.X = X
        

    # def encode_data_short( self, seq_len,  unique_labels, is_binary=True,  spec_neg_sam=True, proteinbert=True):        
    #     data_seq = [d['seq'] for d in self.records]
    #     data_label = [ d['label'] for d in self.records]
    #     half_len = (seq_len-2)//2
    #     other_token_index = additional_token_to_index['<OTHER>']
    #     # data_uid = [d['uid'] for d in self.records]
    #     if is_binary:
    #         all_Y = []
    #         all_X = []
    #         all_wei = []

    #         for ul in unique_labels:
    #             Y = []
    #             X = []
    #             # sample_weights = np.zeros((len(data_seq), seq_len))
    #             for i, seq in enumerate(data_seq):
    #                 ptm_type = set()
    #                 pos_ind = []
    #                 for j, lbl in enumerate(data_label[i]):
    #                     if lbl['ptm_type']==ul:
    #                         Y.append(1)                            
    #                         ptm_type = ptm_type.union(seq[lbl['site']])
    #                         pos_ind.append(lbl['site'])
    #                         # retrieval seq where ptm happens in the middle
    #                         s = retri_seq(lbl['site'], half_len, seq, other_token_index)
    #                         assert len(s)==seq_len
    #                         X.append(np.array(s))
    #                 if spec_neg_sam:
    #                     if len(ptm_type)>0:
    #                         neg_ind = set([ii for ii, aa in enumerate(seq) if aa in list(ptm_type)])
    #                         # if evaluate:
    #                         neg_ind = np.array(list(neg_ind - set(pos_ind))).astype(int)
    #                         for ni in neg_ind:
    #                             Y.append(0)
    #                             s = retri_seq(ni, half_len, seq, other_token_index)
    #                             X.append(s)
    #                         # else:
    #                         #     neg_ind = np.array(list(neg_ind - set(pos_ind))).astype(int)
    #                         #     if len(neg_ind)>0:
    #                         #         k = min(len(pos_ind), len(neg_ind))
    #                         #         neg_ind = np.random.choice(neg_ind, k, False)
    #                         #         sample_weights[i, neg_ind+1] = 1
    #             all_Y.append(np.array(Y))
    #             all_wei.append(np.ones(np.array(Y).shape))
    #             if proteinbert:
    #                 all_X.append([
    #                     np.array(X),np.zeros((len(X), 8943), dtype = np.int8)])
    #             else:
    #                 all_X.append(np.array(X))
    #         Y = all_Y
    #         X = all_X   
                   
    #     self.Y  = Y
    #     self.X = X
    #     self.sample_weights = all_wei
        # pdb.set_trace()

    # def batch_iter(self, is_random=True):
    #     if is_random:
    #         random.shuffle(self.records)
    #     cur_seq, cur_uid,  cur_lbl = [], [], []
    #     cur_cnt = 0
    #     for data in self.records:
    #         cur_lbl.append([data['label']])
    #         cur_uid.append(self.pad(data['uid']))
    #         cur_seq.append(self.pad(data['seq']))
    #         cur_cnt += 1
    #         if cur_cnt == self.batch_size:
    #             yield {
    #                     'label': np.array(cur_lbl),
    #                     'seq':cur_seq,
    #                     'label':cur_lbl}
    #             cur_cnt = 0
    #             cur_seq, cur_uid,  cur_lbl = [], [], []
    #     yield {
    #             'label': np.array(cur_lbl),
    #             'seq':cur_seq,
    #             'label':cur_lbl}




class PTMDataGenerator(tf.keras.utils.Sequence):
    def __init__(self, dat, seq_len, batch_size=32,  unique_labels=None,graph=False, shuffle=True):
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.dat = dat
        self.list_id = np.arange(self.dat.Y.shape[0])
        self.unique_labels = unique_labels
        self.seq_len = seq_len
        self.graph = graph
        self.on_epoch_end()

    def __len__(self):
        # number of batch per epoch
        return len(self.index) // self.batch_size

    def __getitem__(self, index):
        index = self.index[index * self.batch_size:(index + 1) * self.batch_size]
        batch = [self.list_id[k] for k in index]
        
        X, y, sample_weights = self.__get_data(batch)
        return (X, y, sample_weights)

    def on_epoch_end(self):
        self.index = np.arange(self.dat.Y.shape[0])
        if self.shuffle == True:
            np.random.shuffle(self.index)

    def __get_data(self, batch):
        # batch = np.array(batch)
        X = [x[batch] for x in self.dat.X]  # get batch for all component of X
        y = self.dat.Y[batch] 
        uid = np.array(self.dat.uid)
        uid = uid[batch]
        sample_weights = self.dat.sample_weights[batch]
        # change shape to (batch, seq_len, labels)
        y = y.reshape((len(batch), self.seq_len, -1))
        sample_weights = sample_weights.reshape((len(batch), self.seq_len, -1))

        label_to_index = {str(label): i for i, label in enumerate(self.unique_labels)}

        # To randomly assign negative sample everytime
        for i in range(y.shape[0]):
            for u in self.unique_labels:
                aa = self.dat.label2aa[u]
                seq = [index_to_token[j] for j in X[0][i]]  
                all_neg_index = np.array([j for j,amino in enumerate(seq) if amino in aa], dtype=int)
                # remove positive labels
                pos_index = set(np.array([j for j in range(y.shape[1]) if y[i,j, label_to_index[u]]==1], dtype = int))
                all_neg_index = set(all_neg_index) - pos_index
                all_neg_index = np.array([j for j in all_neg_index])
                n_pos = int(np.sum(sample_weights[i,:,label_to_index[u]]))
                if len(all_neg_index)<1 or n_pos==0:
                    continue
                #pdb.set_trace()
                if n_pos <= len(all_neg_index):#if more pos than neg
                    neg_index = np.array(random.sample(set(all_neg_index), k=1), dtype=int)#n_pos TODO
                else:
                    neg_index = all_neg_index[0]
                sample_weights[i, neg_index, label_to_index[u]] = 1
                # testing TODO: remove
                if n_pos <= len(all_neg_index):
                    pos_y = np.sum(y[i,:, label_to_index[u]][sample_weights[i, :, label_to_index[u]]==1] ==1)
                    neg_y = np.sum(y[i,:, label_to_index[u]][sample_weights[i, :, label_to_index[u]]==1] ==0)
                    # print(pos_y, neg_y)
                    #assert pos_y == neg_y


        y = y.reshape((len(batch),-1, 1))
        sample_weights = sample_weights.reshape((len(batch), -1, 1))# == 1
        
        # add graph
        if self.graph:
            adjs = get_graph(uid, self.seq_len)
            adjs = np.array(adjs)
            X.append(adjs)
        return (X, y, sample_weights)


def get_graph(uid, seq_len):
    adjs = []
    for i in range(len(uid)):
        # get adj
        adj_dir = '/workspace/PTM/Data/Musite_data/Structure/pdb/AF_cont_map/'
        adj = np.load(adj_dir+uid[i]+'.cont_map.npy')
        n = adj.shape[0]
        # pad adj with [0] as 0 for start 
        pad_adj = np.zeros((seq_len, seq_len))
        pad_adj[1:(1+n),1:(1+n)] = adj
        adjs.append(pad_adj)
    adjs = np.array(adjs)
    return adjs


def get_unique_labels(train_set, valid_set, test_set):
    return sorted( set([l['ptm_type'] for d in train_set.records for l in d['label'] ]).union(\
                set([l['ptm_type'] for d in valid_set.records for l in d['label'] ])).union(\
                    set([l['ptm_type'] for d in test_set.records for l in d['label'] ])))


def get_class_weights(train_set, valid_set, test_set, unique_labels):
    class_weights = {u:0 for u in unique_labels}

    for d in train_set.records:
        for l in d['label']:
            class_weights[l['ptm_type']]+=1 
    
    for d in valid_set.records:
        for l in d['label']:
            class_weights[l['ptm_type']]+=1 
    
    for d in test_set.records:
        for l in d['label']:
            class_weights[l['ptm_type']]+=1 
    
    class_weights = [float(class_weights[u]) for u in unique_labels]
    mean_w = sum(class_weights)/len(class_weights)
    class_weights = np.array([mean_w/u for u in class_weights])
    return class_weights



def tokenize_seqs(seqs, seq_len):
    # Note that tokenize_seq already adds <START> and <END> tokens.
    return np.array([seq_tokens + (seq_len - len(seq_tokens)) * [additional_token_to_index['<PAD>']] for seq_tokens in map(tokenize_seq, seqs)], dtype = np.int32)

def retri_seq(site, half_len, seq, other_token_index):
    if site < half_len:
        left_s = seq[0:site+1]
    else:
        left_s = seq[(site-half_len):(site+1)]
    if site + half_len > len(seq):
        right_s = seq[(site+1):len(seq)]
    else:
        right_s = seq[(site+1):(site+half_len+1)]
    left_s = [additional_token_to_index['<START>']] + [aa_to_token_index.get(aa, other_token_index) for aa in parse_seq(left_s)]
    right_s = [aa_to_token_index.get(aa, other_token_index) for aa in parse_seq(right_s)] + [additional_token_to_index['<END>']]
    left_s = (half_len+2 - len(left_s)) * [additional_token_to_index['<PAD>']] + left_s
    right_s = right_s + (half_len+1 - len(right_s)) * [additional_token_to_index['<PAD>']]
    s = left_s + right_s    

    return s

class CategoricalTruePositives(tf.keras.metrics.Metric):

    def __init__(self, num_classes, batch_size,
                 name="categorical_true_positives", **kwargs):
        super(CategoricalTruePositives, self).__init__(name=name, **kwargs)

        self.batch_size = batch_size
        self.num_classes = num_classes    

        self.cat_true_positives = self.add_weight(name="ctp", initializer="zeros")

    def update_state(self, y_true, y_pred, sample_weight):     

        y_mask = tf.reshape(sample_weight, [-1, 13])
        y_true = tf.reshape(y_true,[-1,  13])
        y_pred = tf.reshape(y_pred,[-1,  13])

        y_trues = [y_true[:,i][y_mask[:,i]==1] for i in range(13)]
        y_preds = [y_pred[:,i][y_mask[:,i]==1] for i in range(13)]

        pdb.set_trace()
        for i in range(13):
            print(pd.DataFrame(confusion_matrix(y_trues[i], y_preds[i]>=0.5, labels = np.array([0,1])), index = ['0','1'],columns = ['0','1']))

    def result(self):

        return None#self.cat_true_positives