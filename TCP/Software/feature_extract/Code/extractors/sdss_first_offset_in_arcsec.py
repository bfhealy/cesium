from ..FeatureExtractor import ContextFeatureExtractor

class sdss_first_offset_in_arcsec(ContextFeatureExtractor): 
        """What is the offset of the first source?"""
        active = True
        extname = 'sdss_first_offset_in_arcsec' #extractor's name
        light_cutoff = 0.2 ## dont report anything farther away than this in arcmin
        
        verbose = False
        def extract(self):
                n = self.fetch_extr('intersdss')
                
                if n is None:
                    if self.verbose:
                        print("Nothing in the sdss extractor")
                    return None
                    
                if "in_footprint" not in n:
                    if self.verbose:
                        print("No footprint info in the sdss extractor. Should never happen.")
                    return None
                
                if not n['in_footprint']:
                    if self.verbose:
                        print("Not in the footprint")
                    return None

                if "first_offset_in_arcsec" not in n:
                    if self.verbose:
                        print("Desired parameter was not determined")
                    return None

                if "dist_in_arcmin" not in n:
                    if self.verbose:
                        print("Desired parameter was not determined")
                    return None
                    
                if n["dist_in_arcmin"] > self.light_cutoff:
                    return None
                else:
                    rez = n["first_offset_in_arcsec"]
                if self.verbose:
                        print(n)
                return rez