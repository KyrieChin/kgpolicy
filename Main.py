import os
import sys
from time import time
import numpy as np
import random
import torch
import torch.nn as nn
from torch.autograd import Variable
from tqdm import tqdm

from utility.parser import parse_args
from utility.test_model import test
from utility.helper import early_stopping, ensureDir

from dataloader.data_processor import CKG_Data
from dataloader.loader_advnet import build_loader

from recommender.MF import MF
from sampler.Adversarial_Sampler import AdvNet

from utility.test_model import args_config, CKG


def train_one_epoch(recommender, train_loader, recommender_optim, cur_epoch):
    loss, base_loss, reg_loss = 0, 0, 0
    """Train one epoch"""
    tbar = tqdm(train_loader, ascii=True)
    for _, batch_data in enumerate(tbar):
        tbar.set_description('Epoch {}'.format(cur_epoch))

        if torch.cuda.is_available():
            batch_data = {k: v.cuda(non_blocking=True) for k, v in batch_data.items()}

        """Train recommender using negtive item provided by sampler"""
        recommender_optim.zero_grad()
        # selected_neg_items, selected_neg_prob = sampler(batch_data)

        # batch_data['neg_id'] = selected_neg_items

        reward_batch, loss_batch, base_loss_batch, reg_loss_batch = recommender(batch_data)
        loss_batch.backward()
        recommender_optim.step()
        # recommender.constraint()

        """Train sampler network"""
        # sampler_optimer.zero_grad()
        # reinforce_loss = torch.sum(Variable(reward_batch) * selected_neg_prob)
        # reinforce_loss.backward()
        # sampler_optimer.step()
        # sampler.constraint()

        loss += loss_batch
        base_loss += base_loss_batch
        reg_loss += reg_loss_batch
        # print(torch.mean(reward_batch))
    
    print("Epoch {}: \n Training loss: [{} = {} + {}]\n".format(cur_epoch, loss, base_loss, reg_loss))
    
    return loss, base_loss, reg_loss



def train(train_loader, test_loader, data_config, args_config):
    """Build Sampler and Recommender"""
    # sampler = AdvNet(data_config=data_config, args_config=args_config)
    recommender = MF(data_config=data_config, args_config=args_config)

    if torch.cuda.is_available():
        # sampler = sampler.cuda()
        recommender = recommender.cuda()

    # print('Set sampler as: {}'.format(str(sampler)))
    print('Set recommender as: {}'.format(str(recommender)))

    """Build Optimizer"""
    # sampler_optimer = torch.optim.Adam(sampler.parameters(), lr=args_config.lr, weight_decay=args_config.s_decay)
    recommender_optimer = torch.optim.Adam(recommender.parameters(), lr=args_config.lr, weight_decay=args_config.r_decay)

    """Initialize Best Hit Rate"""
    loss_loger, pre_loger, rec_loger, ndcg_loger, hit_loger = [], [], [], [], []
    stopping_step = 0
    should_stop = False
    cur_best_pre_0 = 0.
    t0 = time()

    for epoch in range(args_config.epoch):
        cur_epoch = epoch + 1
        t1 = time()
        loss, base_loss, reg_loss = train_one_epoch(recommender, train_loader, recommender_optimer, cur_epoch)

        """Test"""
        if cur_epoch % args_config.show_step == 0:
            with torch.no_grad():
                t2 = time()
                ret = test(recommender, test_loader)

            t3 = time()
            loss_loger.append(loss)
            rec_loger.append(ret['recall'])
            pre_loger.append(ret['precision'])
            ndcg_loger.append(ret['ndcg'])
            hit_loger.append(ret['hit_ratio'])

            if args_config.verbose > 0:
                perf_str = 'Epoch %d [%.1fs + %.1fs]: \n train==[%.5f=%.5f + %.5f], \n recall=[%.5f, %.5f], ' \
                           '\n precision=[%.5f, %.5f], \n hit=[%.5f, %.5f], \n ndcg=[%.5f, %.5f] \n' % \
                           (epoch, t2 - t1, t3 - t2, loss, base_loss, reg_loss,
                            ret['recall'][0], ret['recall'][-1],
                            ret['precision'][0], ret['precision'][-1],
                            ret['hit_ratio'][0], ret['hit_ratio'][-1],
                            ret['ndcg'][0], ret['ndcg'][-1])
                print(perf_str)

            cur_best_pre_0, stopping_step, should_stop = early_stopping(ret['recall'][0], cur_best_pre_0,
                                                                        stopping_step, expected_order='acc',
                                                                        flag_step=5)

            # *********************************************************
            # early stopping when cur_best_pre_0 is decreasing for ten successive steps.
            if should_stop == True:
                break

    recs = np.array(rec_loger)
    pres = np.array(pre_loger)
    ndcgs = np.array(ndcg_loger)
    hit = np.array(hit_loger)

    best_rec_0 = max(recs[:, 0])
    idx = list(recs[:, 0]).index(best_rec_0)

    final_perf = "Best Iter=[%d]@[%.1f]\trecall=[%s], precision=[%s], hit=[%s], ndcg=[%s]" % \
                 (idx, time() - t0, '\t'.join(['%.5f' % r for r in recs[idx]]),
                  '\t'.join(['%.5f' % r for r in pres[idx]]),
                  '\t'.join(['%.5f' % r for r in hit[idx]]),
                  '\t'.join(['%.5f' % r for r in ndcgs[idx]]))
    print(final_perf)

if __name__ == '__main__':
    # fix the random seed.
    seed = 2020
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    # set the gpu id.
    if torch.cuda.is_available():
        torch.cuda.set_device(args_config.gpu_id)

    # initialize the data config.
    data_config = {'n_users': CKG.n_users,'n_items': CKG.n_items,
                   'n_relations': CKG.n_relations + 2, 'n_entities': CKG.n_entities, }

    train_loader, test_loader = build_loader(args_config=args_config)
    train(train_loader=train_loader, test_loader=test_loader,
          data_config=data_config, args_config=args_config)

