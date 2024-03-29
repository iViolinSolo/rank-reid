from __future__ import division, print_function, absolute_import

import os

from keras.callbacks import ModelCheckpoint

import utils.cuda_util0
from random import shuffle

import numpy as np
import tensorflow as tf
from keras.applications.resnet50 import ResNet50
from keras.applications.resnet50 import preprocess_input
from keras.backend.tensorflow_backend import set_session
from keras.initializers import RandomNormal
from keras.layers import Dense, Flatten, Dropout, Conv2D, Reshape, Softmax
from keras.layers import Input
from keras.models import Model
from keras.optimizers import SGD, Adagrad
from keras.preprocessing import image
from keras.preprocessing.image import ImageDataGenerator
from keras.utils.np_utils import to_categorical
from keras.utils import multi_gpu_model

from baseline.img_utils import get_random_eraser, crop_generator
from utils.const import PROJECT_ROOT_PATH, DATASET_ROOT_PATH
from utils.hparams import img_width, img_height


def load_mix_data(LIST, TRAIN):
    images, labels = [], []
    with open(LIST, 'r') as f:
        last_label = -1
        label_cnt = -1
        last_type = ''
        for line in f:
            line = line.strip()
            img = line
            lbl = line.split('_')[0]
            cur_type = line.split('.')[-1]
            if last_label != lbl or last_type != cur_type:
                label_cnt += 1
            last_label = lbl
            last_type = cur_type
            img = image.load_img(os.path.join(TRAIN, img), target_size=[img_height, img_width])
            img = image.img_to_array(img)
            img = np.expand_dims(img, axis=0)
            img = preprocess_input(img)

            images.append(img[0])
            labels.append(label_cnt)

    img_cnt = len(labels)
    shuffle_idxes = range(img_cnt)
    shuffle(shuffle_idxes)
    shuffle_imgs = list()
    shuffle_labels = list()
    for idx in shuffle_idxes:
        shuffle_imgs.append(images[idx])
        shuffle_labels.append(labels[idx])
    images = np.array(shuffle_imgs)
    labels = to_categorical(shuffle_labels)
    return images, labels


def load_data(LIST, TRAIN):
    images, labels = [], []
    with open(LIST, 'r') as f:
        last_label = -1
        label_cnt = -1
        for line in f:
            line = line.strip()
            img = line
            lbl = line.split('_')[0]
            if last_label != lbl:
                label_cnt += 1
            last_label = lbl
            img = image.load_img(os.path.join(TRAIN, img), target_size=[img_height, img_width])
            img = image.img_to_array(img)
            img = np.expand_dims(img, axis=0)
            img = preprocess_input(img)

            images.append(img[0])
            labels.append(label_cnt)

    img_cnt = len(labels)
    shuffle_idxes = list(range(img_cnt))
    shuffle(shuffle_idxes)
    shuffle_imgs = list()
    shuffle_labels = list()
    for idx in shuffle_idxes:
        shuffle_imgs.append(images[idx])
        shuffle_labels.append(labels[idx])
    images = np.array(shuffle_imgs)
    labels = to_categorical(shuffle_labels)
    return images, labels


def softmax_model_pretrain(train_list, train_dir, class_count, target_model_path, use_multi_gpu: int = None):
    # ========
    batch_size = 16
    n_epoch = 40

    images, labels = load_data(train_list, train_dir)

    os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.Session(config=config)
    set_session(sess)

    # load pre-trained resnet50
    # this is under keras 2.2.0
    # base_model = ResNet50(weights='imagenet', include_top=False, input_tensor=Input(shape=(224, 224, 3)))
    # this is upper than keras 2.2.0
    base_model = ResNet50(include_top=False, weights='imagenet', input_tensor=Input(shape=(img_height, img_width, 3)), pooling='avg')

    x = base_model.output
    # x = Flatten(name='flatten')(x)
    x = Dropout(0.5)(x)
    x = Dense(class_count, activation='softmax', name='fc8', kernel_initializer=RandomNormal(mean=0.0, stddev=0.001))(x)
    net = Model(inputs=[base_model.input], outputs=[x])

    for layer in net.layers:
        layer.trainable = True

    if use_multi_gpu is not None:
        if type(use_multi_gpu) == int and use_multi_gpu > 1:
            net = multi_gpu_model(net, gpus=use_multi_gpu)

    net.summary()
    print('-=' * 60)
    print('Viva la Vida')
    print('-=' * 60)

    # pretrain
    # batch_size = 16
    train_cnt = len(labels)
    train_datagen = ImageDataGenerator(shear_range=0.2, width_shift_range=0.2, height_shift_range=0.2,
                                       horizontal_flip=0.5).flow(images[:train_cnt // 10 * 9],
                                                                 labels[:train_cnt // 10 * 9], batch_size=batch_size)

    # train_datagen = ImageDataGenerator().flow(
    #     images[:train_cnt//10*9], labels[:train_cnt//10*9], batch_size=batch_size)
    val_datagen = ImageDataGenerator(horizontal_flip=0.5).flow(images[train_cnt // 10 * 9:],
                                                               labels[train_cnt // 10 * 9:], batch_size=batch_size)

    save_best = ModelCheckpoint(target_model_path, monitor='val_acc', save_best_only=True)
    net.compile(optimizer=SGD(lr=0.001, momentum=0.9), loss='categorical_crossentropy', metrics=['accuracy'])
    net.fit_generator(
        train_datagen,
        steps_per_epoch=int(train_cnt / 20 * 19 / batch_size + 1),
        epochs=n_epoch,
        validation_data=val_datagen,
        validation_steps=int(train_cnt / 20 / batch_size + 1),
        callbacks=[save_best]
    )
    net.save(target_model_path)


def softmax_pretrain_on_dataset(source, project_path=PROJECT_ROOT_PATH, dataset_parent=DATASET_ROOT_PATH,
                                multi_gpus: int = None):
    if source == 'market':
        train_list = project_path + '/dataset/market_train.list'
        train_dir = dataset_parent + '/Market-1501-v15.09.15/_rerank/train'
        class_count = 751
    elif source == 'grid':
        train_list = project_path + '/dataset/grid_train.list'
        train_dir = dataset_parent + '/grid_label'
        class_count = 250
    elif source == 'cuhk':
        train_list = project_path + '/dataset/cuhk_train.list'
        train_dir = dataset_parent + '/cuhk01'
        class_count = 971
    elif source == 'viper':
        train_list = project_path + '/dataset/viper_train.list'
        train_dir = dataset_parent + '/viper'
        class_count = 630
    elif source == 'duke':
        train_list = project_path + '/dataset/duke_train.list'
        train_dir = dataset_parent + '/DukeMTMC-reID/train'
        class_count = 702
    elif 'grid-cv' in source:
        cv_idx = int(source.split('-')[-1])
        train_list = project_path + '/dataset/grid-cv/%d.list' % cv_idx
        train_dir = dataset_parent + '/underground_reid/cross%d/train' % cv_idx
        class_count = 125
    elif 'mix' in source:
        train_list = project_path + '/dataset/mix.list'
        train_dir = dataset_parent + '/cuhk_grid_viper_mix'
        class_count = 250 + 971 + 630
    else:
        train_list = 'unknown'
        train_dir = 'unknown'
        class_count = -1
    softmax_model_pretrain(train_list, train_dir, class_count, '../pretrain/' + source + '_softmax_pretrain.h5',
                           use_multi_gpu=multi_gpus)


if __name__ == '__main__':
    # sources = ['market', 'grid', 'cuhk', 'viper']
    sources = ['market']
    for source in sources:
        softmax_pretrain_on_dataset(source, multi_gpus=None)
