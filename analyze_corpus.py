from sklearn.feature_extraction.text import CountVectorizer
from progressbar import progressbar
import networkx as nx
import pandas as pd
import pdb
import os


def main():
    df=pd.read_csv('https://theunitedstates.io/congress-legislators/legislators-current.csv')
    df.at[df.twitter =='SenSanders', 'party'] = 'Democrat' # for ideological purposes
    df = df[df.type=='sen']
    df = df[~df.votesmart_id.isna()]

    texts_df = get_all_texts(df)

    tf_vectorizer = CountVectorizer(max_df=0.8, min_df=50,
                                ngram_range = (1,2),
                                binary=False,
                                stop_words='english')

    print("Fitting...")
    tf_vectorizer.fit(texts_df.text.tolist())
    term_frequencies = tf_vectorizer.fit_transform(texts_df.text.tolist())
    phrases_df = pd.DataFrame(data=tf_vectorizer.get_feature_names(),columns=['phrase'])
    phrases_df['total_occurrences']=term_frequencies.sum(axis=0).T
    phrases_df.sort_values(by='total_occurrences',ascending=False).head(20).to_csv('output/top_20_overall.csv',index=False)

    print("Analyzing partisan patterns...")
    dem_tfs = tf_vectorizer.transform(texts_df[texts_df.party=='Democrat'].text.tolist())
    rep_tfs = tf_vectorizer.transform(texts_df[texts_df.party=='Republican'].text.tolist())
    n_dem_docs = dem_tfs.shape[0]
    n_rep_docs = rep_tfs.shape[0]
    print("{} Dem docs, {} Rep docs".format(n_dem_docs, n_rep_docs))

    total_dem_tfs = dem_tfs.sum(axis=0)
    total_rep_tfs = rep_tfs.sum(axis=0)
    total_tfs = total_dem_tfs + total_rep_tfs
    p_dem = total_dem_tfs / n_dem_docs
    p_rep = total_rep_tfs / n_rep_docs

    bias = (p_rep - p_dem) / (p_rep + p_dem)

    phrases_df['bias_score'] = bias.T
    phrases_df['p_dem'] = p_dem.T
    phrases_df['p_rep'] = p_rep.T
    phrases_df['n_dem'] = total_dem_tfs.T
    phrases_df['n_rep'] = total_rep_tfs.T 

    print('Counting senators...')
    #phrases_df['n_senators'] = phrases_df.apply(lambda x: len(texts_df[texts_df.text.str.contains(x.phrase)].person.unique()),axis=1)
    #phrases_df = phrases_df[phrases_df.n_senators > 2]


    phrases_df.sort_values(by='total_occurrences',ascending=False).to_csv('output/all_phrases.csv',index=False)

    print("Most Democratic...")
    top_dem = phrases_df.sort_values(by='bias_score',ascending=True).head(200).copy()
    top_dem['n_senators'] = top_dem.apply(lambda x: len(texts_df[texts_df.text.str.contains(x.phrase)].person.unique()),axis=1)
    top_dem = top_dem[top_dem.n_senators > 2]
    top_dem.head(20).to_csv('output/top_20_democrat.csv',index=False)


    print("Most Republican:")
    top_rep = phrases_df.sort_values(by='bias_score',ascending=False).head(200).copy()
    top_rep['n_senators'] = top_rep.apply(lambda x: len(texts_df[texts_df.text.str.contains(x.phrase)].person.unique()),axis=1)
    top_rep = top_rep[top_rep.n_senators > 2]
    top_rep.head(20).to_csv('output/top_20_republican.csv',index=False)




def make_figures(texts_df):
    jan = texts_df[texts_df.title.str.contains('January')]






def get_all_texts(df):
    texts_list = []
    for row in df.itertuples():
        n_tweets = 0
        print("Reading in {}...".format(row.full_name))
        all_files = os.listdir('corpus/{}'.format(row.full_name))
        for f in progressbar(all_files):
            with open('corpus/{}/{}'.format(row.full_name,f), 'r') as f:
                title_and_speech = f.read().split('\n\n\n')
                title = title_and_speech[0]
                speech = title_and_speech[1]
            if title.split()[0]=='Tweet': # don't include tweets
                n_tweets += 1
                continue
            text = {'party':row.party, 'person':row.full_name, 'title':title, 'text':speech}
            texts_list.append(text)
        print("{} tweets excluded".format(n_tweets))

    texts_df = pd.DataFrame(texts_list)
    texts_df = texts_df.drop_duplicates(subset=['text'])
    texts_df.sample(100).to_csv('output/all_texts_sample.csv',index=False)

    return texts_df



if __name__=='__main__':
    main()
