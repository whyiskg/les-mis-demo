"""Main module."""

from whyis.autonomic import GlobalChangeService
from whyis.datastore import create_id
from whyis.namespace import NS

import flask

import rdflib
import functools
import uuid

from whyis.namespace import sioc_types, sioc, sio, dc, prov, whyis, owl, NS

wd = rdflib.Namespace('http://www.wikidata.org/entity/')

#rel = rdflib.Namespace(NS.local['relation/'])

#ao = rdflib.Namespace()(NS.local['ontology/'])

kgmo = rdflib.Namespace('http://purl.org/twc/kgmo/')

class KGSummarizer(GlobalChangeService):

    activity_class = wd.Q170084 # generalization

    # Wikidata metaclass is Q16889133.
    _input_class = owl.Class
    #http://purl.org/arclight/ontology/ObjectClass
    _ignore_properties = {sio.SIO_000008, sio.SIO_000300}

    _query = '''
select distinct ?resource where {
    ?resource a %s.
    graph ?assertion {
        [] a ?resource.
    }
}'''

    _instance_count_query = '''
    select ?stype (count(distinct ?s) as ?count) where {
      ?s a ?stype.
      ?stype a ?mt.
    } group by ?stype
'''
    # testing query
    _instance_count_query2 = '''
    PREFIX np: <http://www.nanopub.org/nschema#>
    PREFIX sio: <http://semanticscience.org/resource/>
    select ?stype (count(distinct ?s) as ?count) where {
    graph ?assertion {
        ?s a ?subtype.
    }
    ?subtype a ?mt.
    ?subtype rdfs:subClassOf* ?stype.
    } group by ?stype
'''
    
    _link_query = '''
SELECT 
    (count(distinct ?sub) as ?scount) 
    ?stype 
    ?pred 
    ?otype 
    (count(distinct ?obj) as ?ocount) 
    (count(?sub) as ?count)
WHERE {
  ?sub ?pred ?obj .
  ?sub a ?stype.
  ?obj a ?otype.
  ?otype a owl:Class.
}
group by ?stype ?otype ?pred 
order by desc(?count)'''
        
    def getInputClass(self):
        return self._input_class

    def getOutputClass(self):
        return whyis.DefinedClass

    def get_query(self):
        return self._query % self.getInputClass().n3()

    def identify(self, *elements):
        return str(functools.reduce(uuid.uuid5, [uuid.NAMESPACE_URL]+list(elements)))
    
    def get_nanopub(self, graph, identifier=None):
        if identifier is None:
            fileid = flask.current_app.nanopub_manager._reserve_id()
            identifier = flask.current_app.nanopub_manager.prefix[fileid]
            
            nanopub = Nanopublication(identifier=identifier, store = graph.store)
        
            nanopub.nanopub_resource
            nanopub.assertion
            nanopub.provenance
            nanopub.pubinfo
        else:
            nanopub = flask.current_app.nanopub_manager.get(identifier, graph=graph)
            
        return nanopub

    def process(self, i, o):
        rel = rdflib.Namespace(NS.local['relation/'])
        
        instances = dict([
            (r[0], r[1].value) for r in
            i.graph.query(self._instance_count_query, initBindings=dict(mt=self._input_class))
        ])
        
        properties = [r.asdict()
                      for r in i.graph.query(self._link_query, initBindings=dict(stype=i.identifier))
        ]
        nanopubs = {}

        cg = rdflib.ConjunctiveGraph(store=o.graph.store)
        for entry in properties:
            if entry['pred'] in self._ignore_properties:
                continue
            
            s_total_count = float(instances[entry['stype']])
            o_total_count = float(instances.get(entry['otype'],entry['ocount']))
            rel_id = self.identify(entry['stype'],entry['pred'],entry['otype'])

            nanopub_uri = flask.current_app.nanopub_manager.prefix[rel_id]

            
            if nanopub_uri not in nanopubs:
                nanopubs[nanopub_uri] = self.get_nanopub(cg, nanopub_uri)
            nanopub = nanopubs[nanopub_uri]

            relation = nanopub.assertion.resource(rel[rel_id])
            sc = nanopub.assertion.resource(relation.identifier+"_sc")
            rsc = nanopub.assertion.resource(relation.identifier+"_rsc")

            if (relation.identifier, rdflib.RDF.type, kgmo.Relation) not in nanopub.assertion:
                relation.add(rdflib.RDF.type, kgmo.Relation)
                relation.add(kgmo.hasSourceType, entry['stype'])
                relation.add(kgmo.hasTargetType, entry['otype'])
                relation.add(kgmo.property, entry['pred'])
                
                sc.add(rdflib.RDF.type, kgmo.SyllogismConfidence)
                relation.add(sio.SIO_000008, sc) # has attribute

                rsc.add(rdflib.RDF.type, kgmo.ReverseSyllogismConfidence)
                relation.add(sio.SIO_000008, rsc) # has attribute

            sc.set(sio.SIO_000300, rdflib.Literal(entry['scount'].value/s_total_count))
            
            rsc.set(sio.SIO_000300, rdflib.Literal(entry['ocount'].value/o_total_count))
            
