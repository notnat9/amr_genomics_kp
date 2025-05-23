import re
import io
import streamlit as st
from Bio import SeqIO
from Bio.Seq import Seq
from collections import defaultdict
import pandas as pd

def find_all_occurrences(sequence, subseq):
    """
    Generator to find all occurrences of subseq in sequence.
    Yield every start index at which *subseq* appears in *sequence*.

    This is a simple, overlap‑aware generator that repeatedly calls
    `str.find()` starting one nucleotide past the previous hit, so even
    overlapping matches are reported.

    Args:
        sequence (str): The larger string to search (e.g. a chromosome).
        subseq   (str): The motif or k‑mer to locate.

    Yields:
          Yield every position where *subseq* starts inside *sequence*.
    Lets you get overlapping hits as well.
    
    """
    start = 0
    while True:
        pos = sequence.find(subseq, start)
        if pos == -1:
            break
        yield pos
        start = pos + 1

def get_overlapping_genes(features, start_pos, end_pos):
    """
      From a GenBank feature list, pull out any gene/CDS that overlaps the
    given coordinate range.  Returns a list of simple tuples with the
    feature’s tag info.
    """
    hits = []
    for feat in features:
        if feat.type in ["gene", "CDS"]:
            f_start = int(feat.location.start)
            f_end   = int(feat.location.end)
            # Overlap if they share any region
            if not (f_end < start_pos or f_start > end_pos):
                locus_tag = feat.qualifiers.get("locus_tag", ["?"])[0]
                gene = feat.qualifiers.get("gene", ["?"])[0]
                product = feat.qualifiers.get("product", ["?"])[0]
                hits.append((feat.type, f_start, f_end, locus_tag, gene, product))
    return hits

def extract_genes(overlap_hits):
    """
    Extract gene information from overlap_hits.
    Convert raw overlap tuples into a clean list of gene names
    Returns a list of gene descriptions.
    """
    genes = []
    for (ftype, fs, fe, lt, gene, prod) in overlap_hits:
        if gene != "?":
            genes.append(gene)
        elif lt != "?":
            genes.append(lt)
        else:
            genes.append(prod if prod != "?" else "Unknown")
    return genes

def process_gbff(gbff_path, target_unitigs, pca, index_to_unitig, unitig_to_index):
    """
    Process a FASTA file and return a list of tuples:
    (PC_number, Unitig, Reference_ID).

    This searches both forward and reverse complement of the reference.

     Locate “important” unitigs in a FASTA reference and record which
    principal component (PC) they belong to.

    The function searches both the forward strand and its reverse
    complement, and for each unitig also checks its own reverse
    complement.  Every hit is reported; no attempt is made to merge
    overlapping matches.


    """
    matches = []
    try:
        all_ref_records = list(SeqIO.parse(gbff_path, "fasta"))
    except Exception as e:
        st.warning(f"  [WARNING] Could not parse {gbff_path} as FASTA: {e}")
        return matches

    if not all_ref_records:
        st.warning(f"  [WARNING] No FASTA records in {gbff_path}, skipping.")
        return matches

    for rec in all_ref_records:
        rec_id = rec.id
        forward_seq_str = str(rec.seq).upper()
        revcomp_seq_str = str(rec.seq.reverse_complement()).upper()

        for pc_idx, unitigs in target_unitigs.items():
            for utg in unitigs:
                utg_revcomp = str(Seq(utg).reverse_complement())

                # Search forward ref for utg or its revcomp
                for _ in find_all_occurrences(forward_seq_str, utg):
                    matches.append((pc_idx + 1, utg, rec_id))
                for _ in find_all_occurrences(forward_seq_str, utg_revcomp):
                    matches.append((pc_idx + 1, utg, rec_id))

                # Search reverse ref for utg or its revcomp
                for _ in find_all_occurrences(revcomp_seq_str, utg):
                    matches.append((pc_idx + 1, utg, rec_id))
                for _ in find_all_occurrences(revcomp_seq_str, utg_revcomp):
                    matches.append((pc_idx + 1, utg, rec_id))

    return matches


def load_panaroo_csv(filepath):
    """
    Loads the Panaroo gene_presence_absence.csv,
    building a dictionary: cluster_id -> single short gene name.

    If "Non-unique Gene name" has multiple semicolon-separated entries,
   the first one is picked. If that is empty or also 'group_XXXX',
    we fall back to "Annotation". If that's also not helpful,
    we revert to the cluster ID itself.
    """
    df = pd.read_csv(filepath)
    map_dict = {}

    for i, row in df.iterrows():
        cluster_id = str(row["Gene"])  # e.g. "group_14521" or "rplL"
        nonunique = str(row["Non-unique Gene name"])
        annotation = str(row["Annotation"])

        def is_blank_or_nan(s):
            if not s or s.strip().lower() in ["nan", ""]:
                return True
            return False

        short_name = None
        if not is_blank_or_nan(nonunique):
            splitted = [x.strip() for x in nonunique.split(';') if x.strip()]
            first_nonunique = splitted[0] if splitted else ""
            if first_nonunique and not first_nonunique.startswith("group_"):
                short_name = first_nonunique

        if not short_name:
            if not is_blank_or_nan(annotation) and not annotation.lower().startswith("hypothetical"):
                short_name = annotation.split()[0].strip()

        if not short_name or short_name.startswith("group_"):
            short_name = cluster_id

        map_dict[cluster_id] = short_name

    return map_dict


