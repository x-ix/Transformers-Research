# -*- coding: utf-8 -*-
"""Untitled10.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1rVnzEtrsntnEAOWElUC4Zm4CYbtmg_6J
"""

import gc
import torch

gc.collect()
torch.cuda.empty_cache()

"""#Imports and seed stuff

"""

!pip install sentencepiece
!pip install datasets
!pip install keras-preprocessing
!pip install wandb

import random
import torch
import math
import sentencepiece as spm
from datasets import load_dataset
import string
import time
import wandb
import datetime
import os

dataset = load_dataset("roneneldan/TinyStories")

torch.manual_seed(42)

"""#Hyperparameters"""

#PARAMETERS ARE WRONG

#Transformer block
vocab_size = 100 #len(sp) #No. words in sentencepiece
embed_dim = 128 # Hidden embedding dimension
hidden_dim = 256 # Hidden layer size in feed forward network NEEDS TO BE DIVISIBLE BY NUMBER OF HEADS
num_heads = 4 # Number of attention heads
num_layers = 3  # Number of stacked decoder blocks NIL
dropout = 0.1 #self-explanatory

print(vocab_size)

batch_size = 32 # Batch size for training
# max_seq_len = 256 # Maximum sequence length
lr = 1e-4 # Optimizer learning rate
# beta1 = 0.9 # Adam beta1
# beta2 = 0.999 # Adam beta2
# epsilon = 1e-8 # Adam epsilon

# iter = 100 #print loss after x batches
num_epochs = 10

ds_samples = 10000

"""#wandb"""

# Initialise wandb
wandb.init(
  project="oddformer",
  name= "multiheaded_oddformer",
  config={
  "dataset": "sentences.txt",
  "epochs": num_epochs,
  "batch_size": batch_size,
  }
)

wandb.config.update({
  "epochs": num_epochs,
  "batch_size": batch_size,
  "learning_rate": lr
})

"""#Tokenisation"""

#Extract samples from tinystories to train tokeniser
sample_texts = dataset["train"]['text'][:1000]
# take 1000 samples from training set


for i, text in enumerate(sample_texts):
  text = text.lower().strip() # lowercase and remove whitespace
  text = text.translate(str.maketrans('', '', string.punctuation)) # remove punctuation
  sample_texts[i] = text


with open('sentences.txt', 'w') as f:
  for text in sample_texts:
    f.write(text + '\n')
# write samples to sentences.txt

with open('sentences.txt') as f:
    num_lines = sum(1 for line in f)
print(num_lines)

spm.SentencePieceTrainer.Train(f"--input=sentences.txt --model_prefix=sp --vocab_size=100 --model_type=unigram")

import sentencepiece as spm

class TinyStoriesTokenizer:

    def __init__(self, model_path):
        self.sp = spm.SentencePieceProcessor()
        self.sp.load(model_path)
        self.SOS_TOKEN = self.sp.piece_to_id('<s>')
        self.EOS_TOKEN = self.sp.piece_to_id('</s>')
    def encode(self, texts):
        return self.sp.encode(texts, out_type=int)

    def decode(self, ids):
        return self.sp.decode_ids(ids)

    def tokenize(self, text):
        return self.sp.encode_as_pieces(text)

    @property
    def vocab_size(self):
        return self.sp.get_piece_size()

tokenizer = TinyStoriesTokenizer('sp.model')

import shutil
shutil.copy('sp.model', 'tinystories_tokenizer.model')

"""#Dataset handling"""

import pandas as pd
from sklearn.model_selection import train_test_split

# Load full dataset
full_df = pd.DataFrame.from_dict(dataset['train'])

# Take 100k subsample
df = full_df.sample(ds_samples, random_state=42)

# Split data into train, validation, test
train, test = train_test_split(df, test_size=0.1)
train, val = train_test_split(train, test_size=0.2)

# Set batch size
batch_size = 100

# Create tokenizer
tokenizer = TinyStoriesTokenizer('tinystories_tokenizer.model')

# Lists to store tokenized batches
train_tokens = []
val_tokens = []
test_tokens = []

# Function to iterate through batches
def iterate_batches(df, size):
  for i in range(0, len(df), size):
    yield df[i:i+size]

# Train batches
for batch in iterate_batches(train, batch_size):

  texts = batch['text'].values.tolist()

  tokens = tokenizer.encode(texts)

  train_tokens.append(tokens)


# Validation batches
for batch in iterate_batches(val, batch_size):

  texts = batch['text'].values.tolist()

  tokens = tokenizer.encode(texts)

  val_tokens.append(tokens)


# Test batches
for batch in iterate_batches(test, batch_size):

  texts = batch['text'].values.tolist()

  tokens = tokenizer.encode(texts)

  test_tokens.append(tokens)

print(train_tokens[0][:10])
print(len(train_tokens[0]))

# print(train.head())
# print(val.head())
# print(test.head())

!pip show keras-preprocessing

from keras_preprocessing.sequence import pad_sequences

from torch.utils.data import TensorDataset
# Get max sequence length
max_len = max(len(t) for t in train_tokens + val_tokens) + 1

all_train_tokens = [token for batch in train_tokens for token in batch]
all_val_tokens = [token for batch in val_tokens for token in batch]

del train_tokens, val_tokens #ram

# Pad sequences
pad_train_tokens = pad_sequences(all_train_tokens, maxlen=max_len)
pad_val_tokens = pad_sequences(all_val_tokens, maxlen=max_len)

input_seqs = pad_train_tokens[:, :-1]
target_seqs = pad_train_tokens[:, 1:]

input_seqs2 = pad_val_tokens[:, :-1]
target_seqs2 = pad_val_tokens[:, 1:]

del pad_train_tokens #rem

# Convert to tensors
input_tensors = torch.tensor(input_seqs)
target_tensors = torch.tensor(target_seqs)
train_data = TensorDataset(input_tensors, target_tensors)

input_tensors2 = torch.tensor(input_seqs2)
target_tensors2 = torch.tensor(target_seqs2)
val_data = TensorDataset(input_tensors2, target_tensors2)

del input_seqs, target_seqs, input_tensors, target_tensors, pad_val_tokens

print(train_data[10])

from torch.utils.data import DataLoader

# Create DataLoaders
train_loader = DataLoader(train_data, batch_size=batch_size, shuffle=True)
val_loader = DataLoader(val_data, batch_size=batch_size)

"""#Transformer model"""

import torch
import torch.nn as nn

class ScaledDotProductAttention(nn.Module):
    '''
    Scaled dot-product attention mechanism.
    '''

    def __init__(self, dropout):
        super().__init__()
        self.dropout = nn.Dropout(dropout)

    def forward(self, query, key, value, scale=None, attn_mask=None):
        # print(query.shape, key.shape, value.shape)
        # Scale dot product scores
        if scale is None:
            scale = 1 / (key.size(-1) ** 0.5)
        scores = torch.matmul(query, key.transpose(-2, -1)) * scale
        # print("Scores shape:", scores.shape)

        # Apply attention mask
        if attn_mask is not None:
            scores = scores.masked_fill(attn_mask==0, -1e9)
            # print("Scores shape after mask:", scores.shape)

        # Normalize with softmax
        attn_probs = nn.Softmax(dim=-1)(scores)

        # Apply dropout
        attn_probs = self.dropout(attn_probs)

        # Multiply with value vectors
        context = torch.matmul(attn_probs, value)

        return context

class FeedForwardNetwork(nn.Module):

    def __init__(self, embed_dim, hidden_dim, dropout):

        super().__init__()

        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim

        self.linear1 = nn.Linear(embed_dim, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, embed_dim)

        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):

        x = self.linear1(x)
        x = self.relu(x)
        x = self.dropout(x)

        x = self.linear2(x)
        x = self.dropout(x)

        return x

class MultiHeadedAttention(nn.Module):

    def __init__(self, embed_dim, num_heads, dropout):
        super().__init__()

        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads

        self.q_proj = nn.Linear(embed_dim, embed_dim)
        self.k_proj = nn.Linear(embed_dim, embed_dim)
        self.v_proj = nn.Linear(embed_dim, embed_dim)

        self.attention = ScaledDotProductAttention(dropout)

        self.out_proj = nn.Linear(embed_dim, embed_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, query, key, value, attn_mask):

        # Retain shape after projection
        query = self.q_proj(query)
        key = self.k_proj(key)
        value = self.v_proj(value)

        # Split heads by slicing
        head_dim = self.embed_dim // self.num_heads
        q_slices = [query[:,:,i*head_dim:(i+1)*head_dim] for i in range(self.num_heads)]
        k_slices = [key[:,:,i*head_dim:(i+1)*head_dim] for i in range(self.num_heads)]
        v_slices = [value[:,:,i*head_dim:(i+1)*head_dim] for i in range(self.num_heads)]
        # print(q_slices[0].shape)

        # Attention
        scale = self.head_dim ** -0.5
        outputs = [self.attention(q, k, v, scale, attn_mask) for q, k, v in zip(q_slices, k_slices, v_slices)]

        # Recombine heads
        output = torch.cat(outputs, dim=-1)

        attn_out = self.out_proj(output)

        return attn_out

import torch
import torch.nn as nn

class DecoderBlock(nn.Module):

    def __init__(self, embed_dim, hidden_dim, num_heads, dropout):
       super().__init__()

       self.embed_dim = embed_dim
       self.hidden_dim = hidden_dim
       self.num_heads = num_heads
       self.dropout = dropout

       self.attn = MultiHeadedAttention(embed_dim, num_heads, dropout)
       self.ffn = FeedForwardNetwork(embed_dim, hidden_dim, dropout)

       self.norm1 = nn.LayerNorm(embed_dim)
       self.norm2 = nn.LayerNorm(embed_dim)

       self.drop = nn.Dropout(dropout)


    def forward(self, x, mask):

      attn_out = self.attn(query=x, key=x, value=x, attn_mask=mask)
      x = x + self.drop(self.norm1(attn_out))

      ffn_out = self.ffn(x)
      x = x + self.drop(self.norm2(ffn_out))

      return x

class Transformer(nn.Module):

    def __init__(self, vocab_size, embed_dim, hidden_dim, dropout, num_layers, num_heads):

        super().__init__()

        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers  # Add the num_layers hyperparameter
        self.num_heads = num_heads
        self.dropout = dropout


        self.embedding = nn.Embedding(vocab_size, embed_dim)

        self.decoders = nn.ModuleList([DecoderBlock(embed_dim, hidden_dim, num_heads, dropout) for _ in range(num_layers)])

        self.layer_norm = nn.LayerNorm(embed_dim)

        self.out_proj = nn.Linear(embed_dim, vocab_size)


    def get_pos_matrix(self, x): #can be improved/see learned pos encoding & learned angle divisor param (instead of 10000)
        #print(x.shape)
        batch_size, sequence_length = x.shape
        store = torch.zeros((batch_size, sequence_length, self.embed_dim)).to(x.device)
        for pos in range(sequence_length):
            for i in range(0, self.embed_dim, 2):
                denominator = 10000 ** (i / self.embed_dim)
                angles = torch.tensor([pos / denominator])
                store[:, pos, i] = torch.sin(angles)
                if i + 1 < self.embed_dim:
                    store[:, pos, i + 1] = torch.cos(angles)
        return store

    def forward(self, x):

        x = self.embedding(x) + self.get_pos_matrix(x)
        # print("x shape:", x.shape)
        sequence_length = x.shape[1]
        # Create lower triangular mask
        mask = torch.tril(torch.ones(x.shape[0], x.shape[1], x.shape[1])).to(x.device)
        # print("Mask shape:", mask.shape)
        for decoder in self.decoders:
            x = decoder(x, mask)

        x = self.layer_norm(x)

        out = self.out_proj(x)

        return out

"""#Running"""

m = Transformer(vocab_size, embed_dim, hidden_dim, dropout, num_layers, num_heads)
opt = torch.optim.Adam(m.parameters(), lr=0.01)
criterion = nn.CrossEntropyLoss()
print("Parameters: ", m.parameters())

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
m.to(device)

models_dir = 'models'

if not os.path.exists(models_dir):
    os.makedirs(models_dir)
timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
save_path = f"models/{timestamp}_oddformer.pth"

wandb.join()

# Training loop
def train(model, train_loader, optimizer, criterion, eos, sos):

  model.train()

  train_loss = 0
  for X, y in train_loader:
    X = torch.stack([torch.cat([sos, b]) for b in batch])
    Y = torch.stack([torch.cat([b, eos]) for b in batch])
    X, y = X.to(device), y.to(device)

    optimizer.zero_grad()
    outputs = model(X)
    loss = criterion(outputs, y.long())

    loss.backward()
    optimizer.step()

    train_loss += loss.item() * X.size(0)

  return train_loss / len(train_loader.dataset)

# Validation loop
def validate(model, val_loader, criterion, eos, sos):

  model.eval()

  val_loss = 0
  val_acc = 0

  with torch.no_grad():
    for X, y in val_loader:
      X = torch.stack([torch.cat([sos, b]) for b in batch])
      Y = torch.stack([torch.cat([b, eos]) for b in batch])
      X, y = X.to(device), y.to(device)
      outputs = model(X)
      loss = criterion(outputs, y.long())

      val_loss += loss.item() * X.size(0)
      # Per batch accuracy
      preds = torch.argmax(outputs, dim=1)
      batch_acc = (preds == y).float().mean()

      # Accumulate mean accuracy
      val_acc += batch_acc

  val_loss /= len(val_loader.dataset)
  val_acc /= len(val_loader.dataset)

  return val_loss, val_acc

sos = torch.tensor([tokenizer.SOS_TOKEN], dtype=torch.long)
eos  = torch.tensor([tokenizer.EOS_TOKEN], dtype=torch.long)
print(type(sos), sos.shape)
print(type(eos), eos.shape)
# Training
for epoch in range(num_epochs):

  print(f"Epoch {epoch+1}/{num_epochs}")

  train_loss = train(m, train_loader, opt, criterion, eos, sos)
  val_loss, val_acc = validate(m, val_loader, criterion, eos, sos)

  print(f"Train loss: {train_loss:.4f}", f"Val loss: {val_loss:.4f}, Val acc: {val_acc:.2%}")

  wandb.log({
    "epoch": epoch+1,
    "train_loss": train_loss,
    "val_loss": val_loss,
    "val_acc": val_acc
  })

torch.save(m.state_dict(), "weights.pth")
wandb.save("weights.pth")

wandb.finish()

X, y = next(iter(train_loader))
print(X.shape)

sos = torch.tensor([sos]) # sos_id is index of SOS token
x = torch.cat([sos, X[0]])
print(x.shape)

print(m.input_size) # input size of model