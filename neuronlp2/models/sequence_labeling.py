__author__ = 'max'

import torch
import torch.nn as nn
from ..nn import MaskedRNN, MaskedLSTM, MaskedGRU, ChainCRF
from ..nn import Embedding


class BiRecurrentConv(nn.Module):
    def __init__(self, word_dim, num_words, char_dim, num_chars, num_filters, kernel_size,
                 rnn_mode, hidden_size, num_layers, num_labels,
                 embedd_word=None, embedd_char=None, p_in=0.2, p_rnn=0.5):
        super(BiRecurrentConv, self).__init__()

        self.word_embedd = Embedding(num_words, word_dim, init_embedding=embedd_word)
        self.char_embedd = Embedding(num_chars, char_dim, init_embedding=embedd_char)
        self.conv1d = nn.Conv1d(char_dim, num_filters, kernel_size, padding=kernel_size - 1)
        self.dropout_in = nn.Dropout(p=p_in)
        self.dropout_rnn = nn.Dropout(p_rnn)

        if rnn_mode == 'RNN':
            RNN = MaskedRNN
        elif rnn_mode == 'LSTM':
            # RNN = MaskedLSTM
            RNN = nn.LSTM
        elif rnn_mode == 'GRU':
            RNN = MaskedGRU
        else:
            raise ValueError('Unknown RNN mode: %s' % rnn_mode)

        self.rnn = RNN(word_dim + num_filters, hidden_size, num_layers=num_layers,
                       batch_first=True, bidirectional=True, dropout=p_rnn)

        self.dense = nn.Linear(hidden_size * 2, num_labels)

        self.logsoftmax = nn.LogSoftmax()
        self.nll_loss = nn.NLLLoss(size_average=False)

    def forward(self, input_word, input_char, mask, hx=None):
        # [batch, length, word_dim]
        word = self.word_embedd(input_word)

        # [batch, length, char_length, char_dim]
        char = self.char_embedd(input_char)
        char_size = char.size()
        # first transform to [batch *length, char_length, char_dim]
        # then transpose to [batch * length, char_dim, char_length]
        char = char.view(char_size[0] * char_size[1], char_size[2], char_size[3]).transpose(1, 2)
        # put into cnn [batch*length, char_filters, char_length]
        # then put into maxpooling [batch * length, char_filters]
        char, _ = self.conv1d(char).max(dim=2)
        # reshape to [batch, length, char_filters]
        char = char.view(char_size[0], char_size[1], -1)

        # concatenate word and char [batch, length, word_dim+char_filter]
        input = torch.cat([word, char], dim=2)
        # apply dropout
        input = self.dropout_in(input)
        # output from rnn [batch, length, hidden_size]
        output, _ = self.rnn(input) #self.rnn(input, mask)
        # [batch, length, num_labels]
        return self.dense(self.dropout_rnn(output))

    def loss(self, input_word, input_char, target, mask, hx=None, leading_symbolic=0):
        # [batch, length, num_labels]
        output = self.forward(input_word, input_char, mask, hx)
        # preds = [batch, length]
        _, preds = torch.max(output[:, :, leading_symbolic:], dim=2)
        preds += leading_symbolic

        output_size = output.size()
        # [batch * length, num_labels]
        output_size = (output_size[0] * output_size[1], output_size[2])
        output = output.view(output_size)
        return self.nll_loss(self.logsoftmax(output) * mask.view(output_size[0], 1), target.view(-1)) / mask.sum(), \
               (torch.eq(preds, target).type_as(mask) * mask).sum(), preds